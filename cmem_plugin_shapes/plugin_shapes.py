"""Generate SHACL node and property shapes from a data graph"""

import json
import re
import tempfile
from collections import OrderedDict
from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_hex
from typing import Any, cast
from urllib.parse import quote_plus
from urllib.request import urlopen
from uuid import NAMESPACE_URL, uuid5

import validators.url
from cmem_client.client import Client
from cmem_client.repositories.graphs import ImportConflictPolicy
from cmem_plugin_base.dataintegration.client import get_client
from cmem_plugin_base.dataintegration.context import (
    ExecutionContext,
    ExecutionReport,
    PluginContext,
)
from cmem_plugin_base.dataintegration.description import (
    Icon,
    Plugin,
    PluginAction,
    PluginParameter,
)
from cmem_plugin_base.dataintegration.entity import Entities
from cmem_plugin_base.dataintegration.parameter.choice import ChoiceParameterType
from cmem_plugin_base.dataintegration.parameter.graph import GraphParameterType
from cmem_plugin_base.dataintegration.parameter.multiline import MultilineStringParameterType
from cmem_plugin_base.dataintegration.plugins import WorkflowPlugin
from cmem_plugin_base.dataintegration.ports import FixedNumberOfInputs
from cmem_plugin_base.dataintegration.types import BoolParameterType, StringParameterType
from rdflib import DCTERMS, FOAF, RDF, RDFS, SH, XSD, Graph, Literal, Namespace, URIRef
from rdflib.namespace import split_uri

from . import __path__

SHUI = Namespace("https://vocab.eccenca.com/shui/")
PREFIX_CC = "https://prefix.cc/popular/all.file.json"
# One request per this many IRIs. The explore API takes the list in the request body,
# and a graph with tens of thousands of properties would otherwise build a body large
# enough for a proxy to refuse.
RESOLVE_BATCH_SIZE = 500
# An action renders into a panel, so its listing is capped - and says when it capped.
MAX_LISTED_IRIS = 1000
MANAGED_CLASSES = (
    SH.NodeShape,
    SH.PrefixDeclaration,
    SH.PropertyGroup,
    SH.PropertyShape,
    SH.SPARQLConstraint,
    SHUI.ChartVisualization,
    SHUI.TableReport,
    SHUI.WidgetIntegration,
    SHUI.WorkflowTrigger,
)
PLUGIN_LABEL = "Generate SHACL shapes from data"
TRUE_SET = {"yes", "true", "t", "y", "1"}
FALSE_SET = {"no", "false", "f", "n", "0"}
EXISTING_GRAPH_ADD = "add"
EXISTING_GRAPH_REPLACE = "replace"
EXISTING_GRAPH_STOP = "stop"
EXISTING_GRAPH_PARAMETER_CHOICES = OrderedDict(
    {
        EXISTING_GRAPH_ADD: "Add - insert the generated shapes into the existing graph",
        EXISTING_GRAPH_REPLACE: "Replace - overwrite the existing graph with the generated shapes",
        EXISTING_GRAPH_STOP: "Stop - abort the workflow when the output graph already exists",
    }
)


def format_namespace(iri: str) -> str:
    """Ensure namespace ends with '/' or '#'"""
    return iri if iri.endswith(("/", "#")) else iri + "/"


def str2bool(value: str) -> bool:
    """Convert string to boolean"""
    value = value.lower()
    if value in TRUE_SET:
        return True
    if value in FALSE_SET:
        return False
    allowed_values = '", "'.join(TRUE_SET | FALSE_SET)
    raise ValueError(f'Expected one of: "{allowed_values}"')


@Plugin(
    label=PLUGIN_LABEL,
    icon=Icon(file_name="shapes.svg", package=__package__),
    description="Generate SHACL node and property shapes from a data graph",
    documentation="""This workflow task generates SHACL (Shapes Constraint Language) node
and property shapes by analyzing the instance data of a knowledge graph. The generated
shapes describe the classes the data uses and the properties each class is used with.

The data graph and the shape catalog are both chosen by IRI parameter rather than by
workflow connection, so the task has neither an input nor an output port. It is a
terminal step: it reads and writes graphs directly and hands nothing on to a following
task.

## What is generated

- A **node shape** for every class that instances are typed with.
- A **property shape** for every property those instances use: object properties in the
  subject → object direction, object properties in the object ← subject direction, whose
  names carry a `←` prefix, and datatype properties, whose values are literals.

Every shape gets an IRI derived from a UUID5 of the class or property it describes, so
within one catalog the same class or property always maps to the same shape. Names and
labels come from the title eccenca Corporate Memory resolves for that class or property.
A description follows wherever one can be resolved - the `rdfs:comment`,
`dcterms:description` or `skos:definition` of the class or property, looked up wherever
it is defined, so a vocabulary graph counts as well as the data graph. A class or
property that nothing describes gets no `sh:description`.

Every property shape carries `shui:showAlways`, and a shape for the object ← subject
direction carries `shui:inversePath` as well. A node shape carries the `foaf:depiction` of
its target class wherever the data graph or the class's own vocabulary offers one. The
catalog itself records the data graph it was generated from, when it was written, and the
classes it manages.

## Caveats

Names, labels and descriptions are requested in English. Where a vocabulary offers no
English text, Corporate Memory answers in whatever language it does have, and the
literal carries that language rather than claiming to be English. A class or property
the deployment knows nothing about falls back to a name built from its IRI, which has
no language at all and is written without a tag.

A property used by several classes gets one property shape, shared by every node shape
that uses it. Its `sh:nodeKind` is decided by the first use the store returns, so a
property carrying IRI values under one class and literal values under another is
described as only one of the two.

`sh:datatype rdf:langString` is added as soon as any value of a property carries a
language tag, however few of them do. A property whose values mix tagged and untagged
literals
therefore gets a shape that its own source data does not satisfy.

Adding to an existing catalog inserts triples and deletes none, so shapes written by an
earlier run stay alongside the new ones.

## Example

Given a data graph typing instances with a vocabulary the deployment knows:

``` turtle
ex:Person123 a ex:Person ;
    ex:name "John" ;
    ex:knows ex:Person456 .
```

the task generates a node shape for `ex:Person`

``` turtle
graph:90ee6e27-59b1-5ac8-9d7a-116c60c6791a a sh:NodeShape ;
  rdfs:label "Person (ex:)"@en ;
  sh:name "Person (ex:)"@en ;
  sh:description "A person."@en ;
  sh:property
    graph:0fcf371d-f99a-5eeb-ab50-6e6b5fbb0e06 ,
    graph:dd5c6728-75a2-5215-8a5d-f9cd4077aaea ;
  sh:targetClass ex:Person .
```

together with a property shape for each of `ex:knows` and `ex:name`, of which the first
reads

``` turtle
graph:0fcf371d-f99a-5eeb-ab50-6e6b5fbb0e06 a sh:PropertyShape ;
  rdfs:label "knows (ex:)"@en ;
  sh:name "knows (ex:)"@en ;
  sh:nodeKind sh:IRI ;
  sh:path ex:knows ;
  shui:showAlways true .
```

""",
    parameters=[
        PluginParameter(
            param_type=GraphParameterType(allow_only_autocompleted_values=False),
            name="data_graph_iri",
            label="Input data graph",
            description="The knowledge graph holding the instance data to analyze.",
        ),
        PluginParameter(
            param_type=GraphParameterType(
                classes=["https://vocab.eccenca.com/shui/ShapeCatalog"],
                allow_only_autocompleted_values=False,
            ),
            name="shapes_graph_iri",
            label="Output shape catalog",
            description="The graph the generated shapes are written to.",
        ),
        PluginParameter(
            param_type=ChoiceParameterType(EXISTING_GRAPH_PARAMETER_CHOICES),
            name="existing_graph",
            label="Handle an existing shape catalog",
            description="What to do when the output shape catalog already exists.",
        ),
        PluginParameter(
            param_type=StringParameterType(),
            name="label",
            label="Output shape catalog label",
            description="The label of the shape catalog. Left empty, a new catalog gets a "
            "generated label, and a catalog being added to keeps the label it has - but a "
            "catalog being replaced is rewritten whole, generated label included. Only a "
            'label tagged "en" or carrying no language tag counts as an existing label, and '
            "only such a label is replaced.",
            advanced=True,
        ),
        PluginParameter(
            param_type=BoolParameterType(),
            name="import_shapes",
            label="Import into the central shape catalog",
            description="If enabled, the generated catalog is imported into the central shape "
            "catalog by adding an `owl:imports` statement to it. Shapes in a catalog the "
            "central one does not import are not picked up.",
        ),
        PluginParameter(
            param_type=BoolParameterType(),
            name="prefix_cc",
            label="Fetch namespace prefixes from prefix.cc",
            description="If enabled, the namespace prefix list is fetched from "
            "https://prefix.cc instead of the local prefix database, falling back to the local "
            "database when the service cannot be reached. Prefixes defined in the project win "
            "over both. Enabling this exposes your IP address to prefix.cc; no other data is "
            "shared. If unsure, leave it disabled. See https://prefix.cc/about.",
            advanced=True,
        ),
        PluginParameter(
            param_type=MultilineStringParameterType(),
            name="ignore_properties",
            label="Properties to ignore",
            description="The properties to leave out of the generated shapes, as IRIs, one "
            "per line.",
            advanced=True,
        ),
        PluginParameter(
            param_type=MultilineStringParameterType(),
            name="ignore_types",
            label="Classes to ignore",
            description="The classes to leave out of the generated shapes, as IRIs, one per line.",
            advanced=True,
        ),
        PluginParameter(
            param_type=BoolParameterType(),
            name="plugin_provenance",
            label="Include task provenance",
            description="If enabled, the shape catalog also records the task that generated "
            "it and the parameter values it ran with. Where the type of the task cannot be "
            "determined, nothing is recorded and the run continues with a warning in the log.",
            advanced=True,
        ),
        PluginParameter(
            param_type=BoolParameterType(),
            name="managed_classes",
            label="Declare the classes the catalog manages",
            description="If enabled, the shape catalog states with `shui:managedClasses` which "
            "classes it manages: node shapes, property shapes, property groups, SPARQL "
            "constraints, prefix declarations, chart visualizations, table reports, widget "
            "integrations and workflow triggers.",
            advanced=True,
        ),
        PluginParameter(
            param_type=BoolParameterType(),
            name="depictions",
            label="Add depictions to node shapes",
            description="If enabled, a node shape is given the `foaf:depiction` of its target "
            "class, where one can be found. The class is looked up in the data graph and in the "
            "graph named by its own namespace, tried both with and without the trailing "
            "separator, because the graph a vocabulary was loaded into is not recorded anywhere. "
            "A class depicted more than once contributes one of its depictions, the same one on "
            "every run.",
            advanced=True,
        ),
        PluginParameter(
            param_type=BoolParameterType(),
            name="omit_namespace_addon",
            label="Omit the namespace prefix from property names",
            description="If enabled, property shape names and labels leave off the trailing "
            'namespace prefix, reading "label" rather than "label (rdfs:)". Node shape names '
            "always keep it.",
            advanced=True,
        ),
    ],
    actions=[
        PluginAction(
            name="get_classes",
            label="Get classes",
            description="Lists the classes used in the input data graph, one IRI per line, "
            "ready to paste into Classes to ignore.",
        ),
        PluginAction(
            name="get_properties",
            label="Get properties",
            description="Lists the properties used in the input data graph, one IRI per line, "
            "ready to paste into Properties to ignore.",
        ),
    ],
)
class ShapesPlugin(WorkflowPlugin):
    """SHACL shapes generation plugin"""

    # A plugin constructor takes one argument per PluginParameter, so its arity is
    # fixed by the plugin's configuration surface, not by a style choice here.
    def __init__(  # noqa: PLR0913, PLR0917
        self,
        data_graph_iri: str,
        shapes_graph_iri: str,
        label: str = "",
        existing_graph: str = EXISTING_GRAPH_STOP,
        import_shapes: bool = False,
        prefix_cc: bool = False,
        ignore_properties: str = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
        ignore_types: str = "",
        plugin_provenance: bool = False,
        omit_namespace_addon: bool = False,
        managed_classes: bool = True,
        depictions: bool = True,
    ) -> None:
        if not validators.url(data_graph_iri):
            raise ValueError("Invalid value for parameter 'Input data graph'")
        self.data_graph_iri = data_graph_iri

        if not validators.url(shapes_graph_iri):
            raise ValueError("Invalid value for parameter 'Output shape catalog'")
        self.shapes_graph_iri = shapes_graph_iri

        if shapes_graph_iri == data_graph_iri:
            raise ValueError("Shapes graph IRI cannot be the same as data graph IRI")

        self.label = label

        existing_graph = existing_graph.lower()
        if existing_graph not in EXISTING_GRAPH_PARAMETER_CHOICES:
            raise ValueError(
                "Invalid value for parameter 'Handle existing output graph'. "
                f"Valid options: {', '.join(EXISTING_GRAPH_PARAMETER_CHOICES.keys())}."
            )
        self.replace = False
        if existing_graph == EXISTING_GRAPH_REPLACE:
            self.replace = True
        self.existing_graph = existing_graph

        self.import_shapes = import_shapes
        self.prefix_cc = prefix_cc

        self.ignore_properties = []
        for _ in filter(None, ignore_properties.split("\n")):
            if not validators.url(_):
                raise ValueError(f"Invalid property IRI ({_}) in parameter 'Properties to ignore'")
            self.ignore_properties.append(_)

        self.ignore_types = []
        for _ in filter(None, ignore_types.split("\n")):
            if not validators.url(_):
                raise ValueError(f"Invalid type IRI ({_}) in parameter 'Types to ignore'")
            self.ignore_types.append(_)

        self.plugin_provenance = plugin_provenance
        self.omit_namespace_addon = omit_namespace_addon
        self.managed_classes = managed_classes
        self.depictions = depictions

        self.shapes_count = 0
        self.input_ports = FixedNumberOfInputs([])
        self.output_port = None

    @staticmethod
    def format_prefixes(
        prefixes: dict, formatted_prefixes: dict | None = None, *, shortest_first: bool = False
    ) -> dict:
        """Format prefix dictionary for consistency

        get_name takes the first prefix of a namespace, so the order within a namespace
        decides how every shape of it is named. ``shortest_first`` orders the prefixes
        contributed by this call by length, which is for the prefix database: it offers
        several prefixes for 171 of its namespaces and is stored sorted alphabetically, so
        taking it as it comes picks "xds:" - a typo entry in prefix.cc - over "xsd:",
        "nsprov:" over "prov:" and "schemas:" over "sdo:". The shortest is the conventional
        one far more often than the alphabetically first is.

        Prefixes a project declares are formatted without it and added first, so they keep
        their precedence over anything the database offers.
        """
        if not formatted_prefixes:
            formatted_prefixes = {}
        grouped: dict = {}
        for prefix, namespace in prefixes.items():
            grouped.setdefault(namespace, []).append(prefix + ":")
        for namespace, candidates in grouped.items():
            if shortest_first:
                candidates.sort(key=lambda candidate: (len(candidate), candidate))
            formatted_prefixes.setdefault(namespace, []).extend(candidates)

        return formatted_prefixes

    def get_prefixes(self) -> dict:
        """Fetch namespace prefixes"""
        prefixes_project = self._get_prefixes(self.context.task.project_id())
        prefixes = self.format_prefixes(prefixes_project)

        prefixes_cc = None
        if self.prefix_cc:
            try:
                res = urlopen(PREFIX_CC)
                self.log.info("prefixes fetched from https://prefix.cc")
                prefixes_cc = json.loads(res.read())
            except Exception as exc:  # noqa: BLE001
                self.log.warning(
                    f"failed to fetch prefixes from https://prefix.cc ({exc}) - using local file"
                )
        if not prefixes_cc or not self.prefix_cc:
            with (Path(__path__[0]) / "prefix_cc.json").open("r", encoding="utf-8") as json_file:
                prefixes_cc = json.load(json_file)
        if prefixes_cc:
            prefixes = self.format_prefixes(prefixes_cc, prefixes, shortest_first=True)

        return {k: tuple(v) for k, v in prefixes.items()}

    def resolve(self, endpoint: str, iris: list[str]) -> dict[str, dict]:
        """Resolve IRIs with one of the explore API helpers

        ``endpoint`` is "titles" or "descriptions". Both take a JSON array of IRIs
        and answer with a mapping of IRI to a record carrying "title" (the resolved
        text), "lang" and "fromIri". No langPrefs is sent, so the deployment answers
        in its default language, English. The descriptions helper leaves an IRI out
        of the mapping entirely when it knows no description for it, while the titles
        helper always answers, falling back to a title built from the IRI itself.
        """
        url = self.client.config.url_explore_api / f"/api/explore/{endpoint}"
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        resolved: dict[str, dict] = {}
        for start in range(0, len(iris), RESOLVE_BATCH_SIZE):
            batch = iris[start : start + RESOLVE_BATCH_SIZE]
            response = self.client.http.post(url=url, headers=headers, json=batch)
            response.raise_for_status()
            resolved.update(cast("dict[str, dict]", response.json()))
        return resolved

    @staticmethod
    def title_record(iri: str, titles: dict) -> dict:
        """Return the resolved title of an IRI, or one standing in for an absent answer

        The titles helper answers for every IRI it is given, but indexing the mapping
        directly made that an assumption which, when it failed, raised KeyError from inside
        the shape loop. The stand-in is what the helper returns for an IRI it knows nothing
        about, so get_name treats it the same way.
        """
        return titles.get(iri) or {"title": iri, "fromIri": True}

    def get_name(self, iri: str, title_record: dict, *, include_namespace: bool = True) -> str:
        """Generate shape name from IRI and its resolved title"""
        results = title_record
        title: str = results["title"]
        try:
            namespace, local_name = split_uri(iri)
        except ValueError as exc:
            raise ValueError(f"Invalid class or property ({iri}).") from exc

        if namespace in self.prefixes:
            prefixes = self.prefixes[namespace]
            prefix = prefixes[0]
            if results["fromIri"]:
                # Nothing in the deployment describes this IRI, so the helper built a title
                # out of the IRI itself. Whatever shape that title takes, the authoritative
                # local name is the one split_uri produced above.
                if title.startswith(prefixes):
                    matched = title.split(":", 1)[0] + ":"
                    title = title[len(matched) :]
                else:
                    title = local_name
            if include_namespace:
                title += f" ({prefix})"
        return title

    @staticmethod
    def name_literal(name: str, title_record: dict) -> Literal:
        """Build the label literal for a name, tagged with the language it was found in

        The titles helper reports the language of the text it resolved, and reports
        none at all for a title it synthesized from the IRI itself (``fromIri``) or
        for a vocabulary that left its label untagged. Neither of those has a
        language, so they are written as plain literals rather than claimed to be
        English.
        """
        lang = title_record.get("lang")
        return Literal(name, lang=lang) if lang else Literal(name)

    def _iri_list(self, context: PluginContext, query: str, variable: str, plural: str) -> str:
        """Run a SELECT returning one variable of IRIs and render it for the action panel

        The result is a fenced code block rather than a plain list: the panel renders
        Markdown, which would run bare lines together into one paragraph, and a block is
        what a user can copy into one of the two ignore parameters unchanged.

        Nothing here may be written as `<iri>`, which Markdown turns into a link. A graph
        IRI is a name and generally not retrievable, so a link on it is an invitation to a
        dead end. The IRIs in the code block are safe, since a fence is not linked.
        """
        # An action is handed its own context, and execute() has not run, so there is no
        # client on the instance yet.
        self.client = get_client(context)
        bindings = json.loads(self._post_sparql(query=query))["results"]["bindings"]
        iris = sorted({binding[variable]["value"] for binding in bindings})
        if not iris:
            return f"No {plural} found in `{self.data_graph_iri}`."
        shown = iris[:MAX_LISTED_IRIS]
        listing = "\n".join(shown)
        header = f"{len(iris)} {plural} found in `{self.data_graph_iri}`"
        if len(shown) < len(iris):
            header += f", showing the first {len(shown)}"
        return f"{header}:\n\n```\n{listing}\n```"

    def get_classes(self, context: PluginContext) -> str:
        """List the classes used in the input data graph"""
        query = f"""
        SELECT DISTINCT ?class
        FROM <{self.data_graph_iri}> {{
            ?subject a ?class .
            FILTER(isIRI(?class))
        }}"""  # noqa: S608
        return self._iri_list(context, query, "class", "classes")

    def get_properties(self, context: PluginContext) -> str:
        """List the properties used in the input data graph

        The two alternatives are the ones get_class_dict draws property shapes from - a
        property of a typed subject, and a property pointing at a typed object - so what is
        listed is what the ignore parameter can actually act on. Neither ignore list is
        applied, since the point is to find out what to put in them.
        """
        query = f"""
        SELECT DISTINCT ?property
        FROM <{self.data_graph_iri}> {{
            {{ ?subject a ?class . ?subject ?property ?object }}
        UNION
            {{ ?object a ?class . ?subject ?property ?object }}
            FILTER(isIRI(?property))
        }}"""  # noqa: S608
        return self._iri_list(context, query, "property", "properties")

    def init_shapes_graph(self) -> Graph:
        """Initialize SHACL shapes graph"""
        shapes_graph = Graph().add((URIRef(self.shapes_graph_iri), RDF.type, SHUI.ShapeCatalog))
        shapes_graph.add(
            (
                URIRef(self.shapes_graph_iri),
                DCTERMS.source,
                URIRef(self.data_graph_iri),
            )
        )
        if self.managed_classes:
            for managed_class in MANAGED_CLASSES:
                shapes_graph.add(
                    (URIRef(self.shapes_graph_iri), SHUI.managedClasses, managed_class)
                )
        return shapes_graph

    @staticmethod
    def namespace_graphs(classes: list[str]) -> list[str]:
        """Graph names to look in for the vocabulary that defines a class

        Which graph a vocabulary was loaded into is recorded nowhere, so the namespace of
        the class IRI is used as the graph name, both as it is and without its trailing
        separator, since either spelling is in use. A class whose IRI cannot be split into
        a namespace and a name contributes nothing here and fails later in get_name, which
        reports it properly.
        """
        graphs: set[str] = set()
        for class_iri in classes:
            with suppress(ValueError):
                namespace, _ = split_uri(class_iri)
                graphs.update((namespace, namespace[:-1]))
        return sorted(graphs)

    def get_depictions(self, classes: list[str]) -> dict[str, URIRef]:
        """Fetch a foaf:depiction for each class that has one

        A FROM naming a graph that does not exist contributes nothing rather than failing,
        which is what makes guessing at the vocabulary graph name safe.
        """
        if not classes:
            return {}
        graphs = "\n".join(
            f"FROM <{graph}>" for graph in [self.data_graph_iri, *self.namespace_graphs(classes)]
        )
        values = " ".join(f"<{class_iri}>" for class_iri in classes)
        query = f"""
        PREFIX foaf: <{FOAF}>
        SELECT ?class ?depiction
        {graphs}
        WHERE {{
            VALUES ?class {{ {values} }}
            ?class foaf:depiction ?depiction
        }}
        ORDER BY ?class ?depiction"""

        depictions: dict[str, URIRef] = {}
        for binding in json.loads(self._post_sparql(query=query))["results"]["bindings"]:
            # a class with several depictions keeps one, and the ordering makes it the same
            # one on every run
            depictions.setdefault(binding["class"]["value"], URIRef(binding["depiction"]["value"]))
        return depictions

    @staticmethod
    def properties_with_lang_string(class_dict: dict) -> set[str]:
        """Return property IRIs that have at least one language-tagged literal value"""
        return {
            prop["property"]
            for properties in class_dict.values()
            for prop in properties
            if prop.get("lang")
        }

    @staticmethod
    def iri_list_to_filter(iris: list[str], name: str = "property", filter_: str = "NOT IN") -> str:
        """List of iris to <iri1>, <iri2>, ..."""
        if filter_ not in ["NOT IN", "IN"]:
            raise ValueError("filter_ must be 'NOT IN' or 'IN'")
        if not re.match(r"^[a-z]+$", name):
            raise ValueError("name must match regex ^[a-z]+$")
        if not iris:
            return ""
        iris_quoted = [f"<{_}>" for _ in iris]

        return f"FILTER (?{name} {filter_} ({', '.join(iris_quoted)}))"

    def get_class_dict(self) -> dict:
        """Retrieve classes and associated properties"""
        query = f"""
        PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
        SELECT DISTINCT ?class ?property ?data ?inverse ?lang
        FROM <{self.data_graph_iri}> {{
            {{
                ?subject a ?class .
                ?subject ?property ?object .
                {self.iri_list_to_filter(self.ignore_properties)}
                {self.iri_list_to_filter(self.ignore_types, name="class")}
                FILTER(isIRI(?class) && isIRI(?property))
                BIND(isLiteral(?object) AS ?data)
                BIND("false" AS ?inverse)
                BIND(LANG(?object) AS ?lang)
            }}
        UNION
            {{
                ?object a ?class .
                ?subject ?property ?object .
                {self.iri_list_to_filter(self.ignore_properties)}
                {self.iri_list_to_filter(self.ignore_types, name="class")}
                FILTER(isIRI(?class) && isIRI(?property))
                BIND("false" AS ?data)
                BIND("true" AS ?inverse)
            }}
        }}
        ORDER BY ?class ?property ?inverse ?data ?lang"""  # noqa: S608

        results = json.loads(self._post_sparql(query=query))

        class_dict: dict = {}
        for binding in results["results"]["bindings"]:
            class_iri = binding["class"]["value"]
            if class_iri not in class_dict:
                class_dict[class_iri] = []
            class_dict[class_iri].append(
                {
                    "property": binding["property"]["value"],
                    "data": str2bool(binding["data"]["value"]),
                    "inverse": str2bool(binding["inverse"]["value"]),
                    "lang": binding.get("lang", {}).get("value", ""),
                }
            )
        return class_dict

    def get_descriptions(self, iris: list[str]) -> dict[str, Literal]:
        """Fetch property descriptions with the description helper of the explore API"""
        descriptions = {}
        for iri, record in self.resolve("descriptions", iris).items():
            # No language means the vocabulary left the text untagged, which is not the
            # same as it being English - name_literal makes the same distinction.
            lang = record.get("lang")
            descriptions[iri] = (
                Literal(record["title"], lang=lang) if lang else Literal(record["title"])
            )
        return descriptions

    def add_property_shape(
        self,
        property_shape_uri: URIRef,
        prop: dict,
        titles: dict,
        descriptions: dict,
        lang_string_properties: set[str],
    ) -> None:
        """Add one property shape to the shapes graph"""
        self.shapes_count += 1
        record = self.title_record(prop["property"], titles)
        name = self.get_name(
            prop["property"],
            record,
            include_namespace=not self.omit_namespace_addon,
        )
        self.shapes_graph.add((property_shape_uri, RDF.type, SH.PropertyShape))
        self.shapes_graph.add((property_shape_uri, SH.path, URIRef(prop["property"])))
        self.shapes_graph.add(
            (property_shape_uri, SH.nodeKind, SH.Literal if prop["data"] else SH.IRI)
        )
        if prop["data"] and prop["property"] in lang_string_properties:
            self.shapes_graph.add((property_shape_uri, SH.datatype, RDF.langString))
        # Only the forward direction. A description is written about the property, so on an
        # inverse path it describes the opposite of what the shape holds - "The family name
        # of a person." on a shape named "← familyName" tells the user exactly the wrong
        # thing.
        description = None if prop["inverse"] else descriptions.get(prop["property"])
        if description is not None:
            self.shapes_graph.add((property_shape_uri, SH.description, description))
        self.shapes_graph.add(
            (property_shape_uri, SHUI.showAlways, Literal("true", datatype=XSD.boolean))
        )
        if prop["inverse"]:
            self.shapes_graph.add(
                (property_shape_uri, SHUI.inversePath, Literal("true", datatype=XSD.boolean))
            )
            name = "← " + name
        name_literal = self.name_literal(name, record)
        self.shapes_graph.add((property_shape_uri, SH.name, name_literal))
        self.shapes_graph.add((property_shape_uri, RDFS.label, name_literal))

    def create_shapes(self) -> None:
        """Create SHACL node and property shapes"""
        class_uuids = set()
        prop_uuids = set()
        class_dict = self.get_class_dict()
        lang_string_properties = self.properties_with_lang_string(class_dict)
        property_iris = sorted(
            {prop["property"] for properties in class_dict.values() for prop in properties}
        )
        # One batched helper call each, rather than one request per IRI from inside
        # the loop below.
        iris = sorted(set(class_dict)) + property_iris
        titles = self.resolve("titles", iris)
        descriptions = self.get_descriptions(iris)
        depictions = self.get_depictions(sorted(class_dict)) if self.depictions else {}
        for cls, properties in class_dict.items():
            # context.workflow is absent in some contexts, the test ones among them, so the
            # check has to be guarded rather than assumed.
            with suppress(AttributeError):
                if self.context.workflow.status() == "Canceling":
                    self.log.info("cancelled - no shapes are written")
                    return
            class_uuid = uuid5(NAMESPACE_URL, cls)
            node_shape_uri = URIRef(f"{format_namespace(self.shapes_graph_iri)}{class_uuid}")

            if class_uuid not in class_uuids:
                self.shapes_count += 1
                self.shapes_graph.add((node_shape_uri, RDF.type, SH.NodeShape))
                self.shapes_graph.add((node_shape_uri, SH.targetClass, URIRef(cls)))
                record = self.title_record(cls, titles)
                class_name = self.name_literal(self.get_name(cls, record), record)
                self.shapes_graph.add((node_shape_uri, SH.name, class_name))
                self.shapes_graph.add((node_shape_uri, RDFS.label, class_name))
                class_description = descriptions.get(cls)
                if class_description is not None:
                    self.shapes_graph.add((node_shape_uri, SH.description, class_description))
                depiction = depictions.get(cls)
                if depiction is not None:
                    self.shapes_graph.add((node_shape_uri, FOAF.depiction, depiction))
                class_uuids.add(class_uuid)

            for prop in properties:
                prop_uuid = uuid5(
                    NAMESPACE_URL, f"{prop['property']}{'inverse' if prop['inverse'] else ''}"
                )
                property_shape_uri = URIRef(f"{format_namespace(self.shapes_graph_iri)}{prop_uuid}")
                if prop_uuid not in prop_uuids:
                    self.add_property_shape(
                        property_shape_uri, prop, titles, descriptions, lang_string_properties
                    )
                    prop_uuids.add(prop_uuid)
                self.shapes_graph.add((node_shape_uri, SH.property, property_shape_uri))
            # inside the loop: a report emitted once the work is over shows a user nothing
            # while the task runs, which is when they are looking at it
            self.update_execution_report()

    def import_shapes_graph(self) -> None:
        """Import SHACL shapes graph to catalog"""
        query = f"""
        INSERT DATA {{
            GRAPH <https://vocab.eccenca.com/shacl/> {{
                <https://vocab.eccenca.com/shacl/> <http://www.w3.org/2002/07/owl#imports>
                    <{self.shapes_graph_iri}> .
            }}
        }}"""

        self.client.store.sparql.update(query=query)

    def parameter_literal(self, name: str) -> Literal:
        """Return a parameter value as a literal safe to put in a SPARQL update

        Interpolating the value into a quoted string by hand let a quote in, say, the
        catalog label break the update - and a crafted value write triples of its own.
        Literal.n3() escapes it. The two ignore parameters are held as parsed lists, so
        they are written back as the lines the user typed rather than as a Python repr.
        """
        value = self.__dict__[name]
        if isinstance(value, list):
            return Literal("\n".join(value))
        return Literal(str(value))

    def post_provenance(self, now: str) -> None:
        """Post provenance"""
        prov = self.get_provenance()
        if not prov:
            return
        param_sparql = ""
        for name, iri in prov["parameters"].items():
            param_sparql += (
                f"\n<{prov['plugin_iri']}> <{iri}> {self.parameter_literal(name).n3()} ."
            )

        insert_query = f"""
        PREFIX dcterms: <http://purl.org/dc/terms/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        INSERT DATA {{
            GRAPH <{self.shapes_graph_iri}> {{
                <{self.shapes_graph_iri}> dcterms:creator <{prov["plugin_iri"]}> .
                <{prov["plugin_iri"]}> a <{prov["plugin_type"]}>,
                        <https://vocab.eccenca.com/di/CustomTask> ;
                    rdfs:label {Literal(prov["plugin_label"]).n3()} ;
                    dcterms:date "{now}"^^xsd:dateTime .
                {param_sparql}
            }}
        }}"""

        self.client.store.sparql.update(query=insert_query)

    def get_provenance(self) -> dict | None:
        """Get provenance information"""
        plugin_iri = (
            f"http://dataintegration.eccenca.com/{self.context.task.project_id()}/"
            f"{self.context.task.task_id()}"
        )
        project_graph = f"http://di.eccenca.com/project/{self.context.task.project_id()}"

        type_query = f"""
        SELECT ?type {{
            GRAPH <{project_graph}> {{
                <{plugin_iri}> a ?type .
                FILTER(STRSTARTS(STR(?type), "https://vocab.eccenca.com/di/functions/"))
            }}
        }}"""

        result = json.loads(self._post_sparql(query=type_query))

        try:
            plugin_type = result["results"]["bindings"][0]["type"]["value"]
        except IndexError:
            self.log.warning("Could not add provenance data to output graph.")
            return None

        param_split = (
            plugin_type.replace(
                "https://vocab.eccenca.com/di/functions/Plugin_",
                "https://vocab.eccenca.com/di/functions/param_",
            )
            + "_"
        )

        parameter_query = f"""
        SELECT ?parameter {{
            GRAPH <{project_graph}> {{
                <{plugin_iri}> ?parameter ?o .
                FILTER(STRSTARTS(STR(?parameter), "https://vocab.eccenca.com/di/functions/param_"))
            }}
        }}"""

        # A fresh subject per run, derived from the task IRI. Only a suffix this method
        # added itself is replaced: splitting on every underscore ate the task segment
        # whenever the project id contained one, and produced the bare relative reference
        # "_<hex>" when neither id did.
        new_plugin_iri = f"{re.sub(r'_[0-9a-f]{16}$', '', plugin_iri)}_{token_hex(8)}"
        label = f"{PLUGIN_LABEL} plugin"
        result = json.loads(self._post_sparql(query=parameter_query))

        prov = {
            "plugin_iri": new_plugin_iri,
            "plugin_label": label,
            "plugin_type": plugin_type,
            "parameters": {},
        }

        for binding in result["results"]["bindings"]:
            param_iri = binding["parameter"]["value"]
            param_name = param_iri.split(param_split)[1]
            prov["parameters"][param_name] = param_iri

        return prov

    def create_graph(self) -> str:
        """Create or replace SHACL shapes graph"""
        self.create_label()
        ntriples = self.shapes_graph.serialize(format="nt", encoding="utf-8").decode()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".nt", delete=False, encoding="utf-8"
        ) as f:
            f.write(ntriples)
            tmp_path = f.name
        try:
            self.client.graphs.import_item(
                path=Path(tmp_path),
                key=self.shapes_graph_iri,
                on_conflict=ImportConflictPolicy.REPLACE
                if self.replace
                else ImportConflictPolicy.FAIL,
            )
        finally:
            Path(tmp_path).unlink(missing_ok=True)
        now = datetime.now(UTC).isoformat(timespec="milliseconds")[:-6] + "Z"
        query_add_created = f"""
        PREFIX dcterms: <http://purl.org/dc/terms/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        INSERT DATA {{
            GRAPH <{self.shapes_graph_iri}> {{
                <{self.shapes_graph_iri}> dcterms:created "{now}"^^xsd:dateTime
            }}
        }}"""

        self.client.store.sparql.update(query=query_add_created)
        return now

    def create_label(self) -> None:
        """Create label in shapes graph"""
        label = self.label or f"Shapes for {self.data_graph_iri}"
        self.shapes_graph.add(
            (
                URIRef(self.shapes_graph_iri),
                RDFS.label,
                Literal(label, lang="en"),
            )
        )

    def add_to_graph(self) -> str:
        """Add SHACL shapes to existing graph"""
        query_ask_label = f"""
        PREFIX  rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        ASK {{
            GRAPH <{self.shapes_graph_iri}> {{
                 <{self.shapes_graph_iri}> rdfs:label ?label
                 FILTER(LANG(?label) in ("en", ""))
            }}
        }}"""

        query_remove_label = f"""
        PREFIX  rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        DELETE {{
            GRAPH <{self.shapes_graph_iri}> {{
                 <{self.shapes_graph_iri}> rdfs:label ?label
            }}
        }}
        WHERE {{
            GRAPH <{self.shapes_graph_iri}> {{
                 <{self.shapes_graph_iri}> rdfs:label ?label
                 FILTER(LANG(?label) in ("en", ""))
            }}
        }}"""

        has_label = json.loads(self._post_sparql(query=query_ask_label)).get("boolean", False)
        if self.label and has_label:
            self.client.store.sparql.update(query=query_remove_label)
        if self.label or not has_label:
            self.create_label()

        # The catalog level statements this task owns are replaced rather than added to.
        # Adding inserts and deletes nothing, so without this the managed classes of an
        # earlier run would survive being switched off, and re-running would keep piling
        # the same nine triples onto a catalog that already had them.
        self.client.store.sparql.update(
            query=f"""
        PREFIX shui: <https://vocab.eccenca.com/shui/>
        DELETE {{
            GRAPH <{self.shapes_graph_iri}> {{
                <{self.shapes_graph_iri}> shui:managedClasses ?managed_class
            }}
        }}
        WHERE {{
            GRAPH <{self.shapes_graph_iri}> {{
                <{self.shapes_graph_iri}> shui:managedClasses ?managed_class
            }}
        }}"""
        )

        # Same reasoning for the shapes themselves. Every predicate below holds one value
        # per shape, so leaving the old one in place shows the user two names, two labels or
        # two descriptions for one field - which is what happens to a catalog written before
        # names carried the language they were resolved in.
        subjects = " ".join(
            f"<{subject}>"
            for subject in sorted({str(s) for s in self.shapes_graph.subjects()})
            if subject != self.shapes_graph_iri
        )
        if subjects:
            self.client.store.sparql.update(
                query=f"""
        PREFIX sh: <http://www.w3.org/ns/shacl#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        PREFIX foaf: <http://xmlns.com/foaf/0.1/>
        DELETE {{
            GRAPH <{self.shapes_graph_iri}> {{ ?shape ?predicate ?value }}
        }}
        WHERE {{
            GRAPH <{self.shapes_graph_iri}> {{
                VALUES ?shape {{ {subjects} }}
                VALUES ?predicate {{
                    sh:name rdfs:label sh:description sh:nodeKind sh:datatype foaf:depiction
                }}
                ?shape ?predicate ?value
            }}
        }}"""
            )

        query_data = f"""
        INSERT DATA {{
            GRAPH <{self.shapes_graph_iri}> {{
                {self.shapes_graph.serialize(format="nt", encoding="utf-8").decode()}
            }}
        }}"""

        self.client.store.sparql.update(query=query_data)

        now = datetime.now(UTC).isoformat(timespec="milliseconds")[:-6] + "Z"
        query_remove_modified = f"""
        PREFIX dcterms: <http://purl.org/dc/terms/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        DELETE {{
            GRAPH <{self.shapes_graph_iri}> {{
                <{self.shapes_graph_iri}> dcterms:modified ?previous
            }}
        }}
        WHERE {{
            GRAPH <{self.shapes_graph_iri}> {{
                OPTIONAL {{
                    <{self.shapes_graph_iri}> dcterms:modified ?previous
                    FILTER(?previous < xsd:dateTime("{now}"))
                }}
            }}
        }}"""

        self.client.store.sparql.update(query=query_remove_modified)

        query_add_modified = f"""
        PREFIX dcterms: <http://purl.org/dc/terms/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        INSERT {{
            GRAPH <{self.shapes_graph_iri}> {{
                <{self.shapes_graph_iri}> dcterms:modified ?current
            }}
        }}
        WHERE {{
            GRAPH <{self.shapes_graph_iri}> {{
                OPTIONAL {{ <{self.shapes_graph_iri}> dcterms:modified ?datetime }}
            }}
            VALUES ?undef {{ UNDEF }}
            BIND(IF(!BOUND(?datetime), xsd:dateTime("{now}"), ?undef) AS ?current)
        }}"""  # noqa: S608

        self.client.store.sparql.update(query=query_add_modified)
        return now

    def update_execution_report(self) -> None:
        """Update execution report"""
        self.context.report.update(
            ExecutionReport(
                entity_count=self.shapes_count,
                operation="write",
                operation_desc="shapes created",
            )
        )

    def _get_graphs_list(self) -> dict:
        """Return graph IRI → Graph mapping.

        Uses self.client.graphs.fetch_data() which populates the internal store.
        """
        self.client.graphs.fetch_data()
        return dict(self.client.graphs.items())

    def _post_sparql(self, query: str) -> bytes:
        result = self.client.store.sparql.query(query=query)
        return cast("bytes", result.serialize(format="json"))

    def _get_prefixes(self, project_name: str) -> dict[Any, Any]:
        """GET prefixes of a project."""
        url = (
            self.client.config.url_build_api
            / f"/api/workspace/projects/{quote_plus(project_name)}/prefixes"
        )
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        response = self.client.http.get(url=url, headers=headers)
        response.raise_for_status()
        return cast("dict", response.json())

    def execute(self, inputs: Sequence[Entities], context: ExecutionContext) -> None:  # noqa: ARG002
        """Execute plugin"""
        self.context = context
        # not in __init__: a second execute() on the same instance would otherwise report
        # the sum of both runs
        self.shapes_count = 0
        self.update_execution_report()
        self.client = Client.from_context(context=context)
        graphs_list = self._get_graphs_list()
        graph_exists = any(self.shapes_graph_iri == g.iri for g in graphs_list.values())
        if self.existing_graph == EXISTING_GRAPH_STOP and graph_exists:
            raise ValueError(f"Graph <{self.shapes_graph_iri}> already exists.")

        self.prefixes = self.get_prefixes()
        self.shapes_graph = self.init_shapes_graph()
        self.dp_api_endpoint = self.client.config.url_explore_api
        self.create_shapes()
        with suppress(AttributeError):
            if context.workflow.status() == "Canceling":
                return

        if self.existing_graph != "add":
            now = self.create_graph()
        else:
            self.graphs_list = graphs_list
            if self.shapes_graph_iri in self.graphs_list:
                now = self.add_to_graph()
            else:
                now = self.create_graph()
        self.update_execution_report()
        if self.plugin_provenance:
            self.post_provenance(now)
        if self.import_shapes:
            self.import_shapes_graph()
