"""Generate SHACL node and property shapes from a data graph"""

import json
import re
import tempfile
from collections import OrderedDict
from collections.abc import Sequence
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
from cmem_plugin_base.dataintegration.context import ExecutionContext, ExecutionReport
from cmem_plugin_base.dataintegration.description import Icon, Plugin, PluginParameter
from cmem_plugin_base.dataintegration.entity import Entities
from cmem_plugin_base.dataintegration.parameter.choice import ChoiceParameterType
from cmem_plugin_base.dataintegration.parameter.graph import GraphParameterType
from cmem_plugin_base.dataintegration.parameter.multiline import MultilineStringParameterType
from cmem_plugin_base.dataintegration.plugins import WorkflowPlugin
from cmem_plugin_base.dataintegration.ports import FixedNumberOfInputs
from cmem_plugin_base.dataintegration.types import BoolParameterType, StringParameterType
from rdflib import DCTERMS, RDF, RDFS, SH, XSD, Graph, Literal, Namespace, URIRef
from rdflib.namespace import split_uri

from . import __path__

SHUI = Namespace("https://vocab.eccenca.com/shui/")
PREFIX_CC = "https://prefix.cc/popular/all.file.json"
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

The catalog itself records the data graph it was generated from and when it was written.

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
language tag, however few do. A property whose values mix tagged and untagged literals
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

and one property shape for each of `ex:knows` and `ex:name`, the first of them

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
            description="The label of the shape catalog. Left empty, a label is generated for a "
            "new catalog, while an existing one keeps the label it has. Only an existing label "
            'tagged "en" or carrying no language tag counts as one, and only such a label is '
            "replaced.",
        ),
        PluginParameter(
            param_type=BoolParameterType(),
            name="import_shapes",
            label="Import into the central shape catalog",
            description="If enabled, the generated catalog is imported into the central shape "
            "catalog by adding an `owl:imports` statement to it. Shapes in a catalog that is not "
            "imported are never activated and never used.",
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
            label="Include plugin provenance",
            description="If enabled, the shape catalog also records the plugin that generated "
            "it and the parameter values it ran with.",
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

        self.shapes_count = 0
        self.input_ports = FixedNumberOfInputs([])
        self.output_port = None

    @staticmethod
    def format_prefixes(prefixes: dict, formatted_prefixes: dict | None = None) -> dict:
        """Format prefix dictionary for consistency"""
        if not formatted_prefixes:
            formatted_prefixes = {}
        for prefix, namespace in prefixes.items():
            formatted_prefixes.setdefault(namespace, []).append(prefix + ":")

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
            prefixes = self.format_prefixes(prefixes_cc, prefixes)

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
        if not iris:
            return {}
        url = self.client.config.url_explore_api / f"/api/explore/{endpoint}"
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        response = self.client.http.post(url=url, headers=headers, json=iris)
        response.raise_for_status()
        return cast("dict[str, dict]", response.json())

    def get_name(self, iri: str, title_record: dict, *, include_namespace: bool = True) -> str:
        """Generate shape name from IRI and its resolved title"""
        results = title_record
        title: str = results["title"]
        try:
            namespace, _ = split_uri(iri)
        except ValueError as exc:
            raise ValueError(f"Invalid class or property ({iri}).") from exc

        if namespace in self.prefixes:
            prefixes = self.prefixes[namespace]
            prefix = prefixes[0]
            if results["fromIri"]:
                if title.startswith(prefixes):
                    if len(prefixes) > 1:
                        prefix = title.split(":", 1)[0] + ":"
                    title = title[len(prefix) :]
                else:
                    try:
                        title = title.split("_", 1)[1]
                    except IndexError as exc:
                        raise IndexError(f"{results['title']} {prefixes}") from exc
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
        return shapes_graph

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
                BIND("false" AS ?data)
                BIND("true" AS ?inverse)
            }}
        }}"""  # noqa: S608

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
            lang = record.get("lang") or "en"
            descriptions[iri] = Literal(record["title"], lang=lang)
        return descriptions

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
        for cls, properties in class_dict.items():
            class_uuid = uuid5(NAMESPACE_URL, cls)
            node_shape_uri = URIRef(f"{format_namespace(self.shapes_graph_iri)}{class_uuid}")

            if class_uuid not in class_uuids:
                self.shapes_count += 1
                self.shapes_graph.add((node_shape_uri, RDF.type, SH.NodeShape))
                self.shapes_graph.add((node_shape_uri, SH.targetClass, URIRef(cls)))
                class_name = self.name_literal(self.get_name(cls, titles[cls]), titles[cls])
                self.shapes_graph.add((node_shape_uri, SH.name, class_name))
                self.shapes_graph.add((node_shape_uri, RDFS.label, class_name))
                class_description = descriptions.get(cls)
                if class_description is not None:
                    self.shapes_graph.add((node_shape_uri, SH.description, class_description))
                class_uuids.add(class_uuid)

            for prop in properties:
                prop_uuid = uuid5(
                    NAMESPACE_URL, f"{prop['property']}{'inverse' if prop['inverse'] else ''}"
                )
                property_shape_uri = URIRef(f"{format_namespace(self.shapes_graph_iri)}{prop_uuid}")
                if prop_uuid not in prop_uuids:
                    self.shapes_count += 1
                    name = self.get_name(
                        prop["property"],
                        titles[prop["property"]],
                        include_namespace=not self.omit_namespace_addon,
                    )
                    self.shapes_graph.add((property_shape_uri, RDF.type, SH.PropertyShape))
                    self.shapes_graph.add((property_shape_uri, SH.path, URIRef(prop["property"])))
                    self.shapes_graph.add(
                        (property_shape_uri, SH.nodeKind, SH.Literal if prop["data"] else SH.IRI)
                    )
                    if prop["data"] and prop["property"] in lang_string_properties:
                        self.shapes_graph.add((property_shape_uri, SH.datatype, RDF.langString))
                    description = descriptions.get(prop["property"])
                    if description is not None:
                        self.shapes_graph.add((property_shape_uri, SH.description, description))
                    self.shapes_graph.add(
                        (
                            property_shape_uri,
                            SHUI.showAlways,
                            Literal("true", datatype=XSD.boolean),
                        )
                    )
                    if prop["inverse"]:
                        self.shapes_graph.add(
                            (
                                property_shape_uri,
                                SHUI.inversePath,
                                Literal("true", datatype=XSD.boolean),
                            )
                        )
                        name = "← " + name
                    name_literal = self.name_literal(name, titles[prop["property"]])
                    self.shapes_graph.add((property_shape_uri, SH.name, name_literal))
                    self.shapes_graph.add((property_shape_uri, RDFS.label, name_literal))
                    prop_uuids.add(prop_uuid)
                self.shapes_graph.add((node_shape_uri, SH.property, property_shape_uri))

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

    def post_provenance(self, now: str) -> None:
        """Post provenance"""
        prov = self.get_provenance()
        if not prov:
            return
        param_sparql = ""
        for name, iri in prov["parameters"].items():
            param_sparql += f'\n<{prov["plugin_iri"]}> <{iri}> "{self.__dict__[name]}" .'

        insert_query = f"""
        PREFIX dcterms: <http://purl.org/dc/terms/>
        PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        INSERT DATA {{
            GRAPH <{self.shapes_graph_iri}> {{
                <{self.shapes_graph_iri}> dcterms:creator <{prov["plugin_iri"]}> .
                <{prov["plugin_iri"]}> a <{prov["plugin_type"]}>,
                        <https://vocab.eccenca.com/di/CustomTask> ;
                    rdfs:label "{prov["plugin_label"]}" ;
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

        new_plugin_iri = f"{'_'.join(plugin_iri.split('_')[:-1])}_{token_hex(8)}"
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
