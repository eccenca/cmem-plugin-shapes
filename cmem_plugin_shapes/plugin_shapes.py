"""Generate SHACL node and property shapes from a data graph"""

import json
import re
from collections import OrderedDict
from collections.abc import Sequence
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from secrets import token_hex
from urllib.parse import quote_plus
from urllib.request import urlopen
from uuid import NAMESPACE_URL, uuid5

import validators.url
from cmem.cmempy.api import send_request
from cmem.cmempy.config import get_dp_api_endpoint
from cmem.cmempy.dp.proxy.graph import get_graphs_list, post_streamed
from cmem.cmempy.dp.proxy.sparql import post as post_sparql
from cmem.cmempy.dp.proxy.update import post as post_update
from cmem.cmempy.workspace.projects.project import get_prefixes
from cmem_plugin_base.dataintegration.context import ExecutionContext, ExecutionReport
from cmem_plugin_base.dataintegration.description import Icon, Plugin, PluginParameter
from cmem_plugin_base.dataintegration.entity import Entities
from cmem_plugin_base.dataintegration.parameter.choice import ChoiceParameterType
from cmem_plugin_base.dataintegration.parameter.graph import GraphParameterType
from cmem_plugin_base.dataintegration.parameter.multiline import MultilineStringParameterType
from cmem_plugin_base.dataintegration.plugins import WorkflowPlugin
from cmem_plugin_base.dataintegration.ports import FixedNumberOfInputs
from cmem_plugin_base.dataintegration.types import BoolParameterType
from cmem_plugin_base.dataintegration.utils import setup_cmempy_user_access
from rdflib import DCTERMS, RDF, RDFS, SH, XSD, Graph, Literal, Namespace, URIRef
from rdflib.namespace import split_uri

from cmem_plugin_shapes.doc import SHAPES_DOC

from . import __path__

SHUI = Namespace("https://vocab.eccenca.com/shui/")
PREFIX_CC = "https://prefix.cc/popular/all.file.json"
TRUE_SET = {"yes", "true", "t", "y", "1"}
FALSE_SET = {"no", "false", "f", "n", "0"}
LABEL = "Generate SHACL shapes from data"


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
    label=LABEL,
    icon=Icon(file_name="shapes.svg", package=__package__),
    description="Generate SHACL node and property shapes from a data graph",
    documentation=SHAPES_DOC,
    parameters=[
        PluginParameter(
            param_type=GraphParameterType(allow_only_autocompleted_values=False),
            name="data_graph_iri",
            label="Input data graph",
            description="The Knowledge Graph containing the instance data to "
            "be analyzed for the SHACL shapes generation.",
        ),
        PluginParameter(
            param_type=GraphParameterType(
                classes=["https://vocab.eccenca.com/shui/ShapeCatalog"],
                allow_only_autocompleted_values=False,
            ),
            name="shapes_graph_iri",
            label="Output Shape Catalog",
            description="The Knowledge Graph the generated shapes will be added to.",
        ),
        PluginParameter(
            param_type=ChoiceParameterType(
                OrderedDict(
                    {
                        "add": "add result to graph",
                        "replace": "replace existing graph with result",
                        "stop": "stop workflow if output graph exists",
                    }
                )
            ),
            name="existing_graph",
            label="Handle existing output graph",
            description="Add result to the existing graph, overwrite the existing graph with the "
            "result, or stop the workflow if the output graph already exists",
            default_value="stop",
        ),
        PluginParameter(
            param_type=BoolParameterType(),
            name="import_shapes",
            label="Import the output graph into the central Shapes Catalog",
            default_value=False,
        ),
        PluginParameter(
            param_type=BoolParameterType(),
            name="prefix_cc",
            label="Additionally fetch namespace prefixes from prefix.cc",
            default_value=False,
            advanced=True,
        ),
        PluginParameter(
            param_type=MultilineStringParameterType(),
            name="ignore_properties",
            label="Properties to ignore",
            description="Provide the list of properties (as IRIs) to ignore.",
            advanced=True,
        ),
        PluginParameter(
            param_type=BoolParameterType(),
            name="plugin_provenance",
            label="Include plugin provenance",
            description="Add information about the plugin and plugin settings to the shapes graph.",
            advanced=True,
        ),
    ],
)
class ShapesPlugin(WorkflowPlugin):
    """SHACL shapes generation plugin"""

    def __init__(  # noqa: PLR0913
        self,
        data_graph_iri: str = "",
        shapes_graph_iri: str = "",
        existing_graph: str = "stop",
        import_shapes: bool = False,
        prefix_cc: bool = True,
        ignore_properties: str = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
        plugin_provenance: bool = True,
    ) -> None:
        if not validators.url(data_graph_iri):
            raise ValueError("Data graph IRI parameter is invalid.")
        self.data_graph_iri = data_graph_iri
        if not validators.url(shapes_graph_iri):
            raise ValueError("Shapes graph IRI parameter is invalid.")
        self.shapes_graph_iri = shapes_graph_iri
        self.ignore_properties = []
        for _ in ignore_properties.split("\n"):
            if not validators.url(_):
                raise ValueError(f"Ignored property IRI invalid: '{_}'")
            self.ignore_properties.append(_)
        self.existing_graph = existing_graph
        self.import_shapes = import_shapes
        self.prefix_cc = prefix_cc
        self.replace = False
        self.plugin_provenance = plugin_provenance
        if existing_graph == "replace":
            self.replace = True
        if existing_graph not in ("stop", "replace", "add"):
            raise ValueError(
                f"Handle existing output graph parameter is invalid '{existing_graph}'."
            )
        self.label = LABEL
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
        prefixes_project = get_prefixes(self.context.task.project_id())
        prefixes = self.format_prefixes(prefixes_project)

        prefixes_cc = None
        if self.prefix_cc:
            try:
                res = urlopen(PREFIX_CC)  # noqa: S310
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

    def get_name(self, iri: str) -> str:
        """Generate shape name from IRI"""
        response = send_request(
            uri=f"{self.dp_api_endpoint}/api/explore/title?resource={quote_plus(iri)}",
            method="GET",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        title_json = json.loads(response)
        title: str = title_json["title"]
        try:
            namespace, _ = split_uri(iri)
        except ValueError as exc:
            raise ValueError(f"Invalid class or property ({iri}).") from exc

        if namespace in self.prefixes:
            prefixes = self.prefixes[namespace]
            prefix = prefixes[0]
            if title_json["fromIri"]:
                if title.startswith(prefixes):
                    if len(prefixes) > 1:
                        prefix = title.split(":", 1)[0] + ":"
                    title = title[len(prefix) :]
                else:
                    try:
                        title = title.split("_", 1)[1]
                    except IndexError as exc:
                        raise IndexError(f"{title_json['title']} {prefixes}") from exc
            title += f" ({prefix})"
        return title

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
        setup_cmempy_user_access(self.context.user)
        query = f"""
            PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
            SELECT DISTINCT ?class ?property ?data ?inverse
            FROM <{self.data_graph_iri}> {{
                {{
                    ?subject a ?class .
                    ?subject ?property ?object .
                    {self.iri_list_to_filter(self.ignore_properties)}
                    BIND(isLiteral(?object) AS ?data)
                    BIND("false" AS ?inverse)
                }}
            UNION
                {{
                    ?object a ?class .
                    ?subject ?property ?object .
                    {self.iri_list_to_filter(self.ignore_properties)}
                    BIND("false" AS ?data)
                    BIND("true" AS ?inverse)
                }}
            }}
        """  # noqa: S608
        results = json.loads(post_sparql(query))

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
                }
            )
        return class_dict

    def create_shapes(self) -> None:
        """Create SHACL node and property shapes"""
        class_uuids = set()
        prop_uuids = set()
        for cls, properties in self.get_class_dict().items():
            class_uuid = uuid5(NAMESPACE_URL, cls)
            node_shape_uri = URIRef(f"{format_namespace(self.shapes_graph_iri)}{class_uuid}")

            if class_uuid not in class_uuids:
                self.shapes_count += 1
                self.shapes_graph.add((node_shape_uri, RDF.type, SH.NodeShape))
                self.shapes_graph.add((node_shape_uri, SH.targetClass, URIRef(cls)))
                name = self.get_name(cls)
                self.shapes_graph.add((node_shape_uri, SH.name, Literal(name, lang="en")))
                self.shapes_graph.add((node_shape_uri, RDFS.label, Literal(name, lang="en")))
                class_uuids.add(class_uuid)

            for prop in properties:
                prop_uuid = uuid5(
                    NAMESPACE_URL, f"{prop['property']}{'inverse' if prop['inverse'] else ''}"
                )
                property_shape_uri = URIRef(f"{format_namespace(self.shapes_graph_iri)}{prop_uuid}")
                if prop_uuid not in prop_uuids:
                    self.shapes_count += 1
                    name = self.get_name(prop["property"])
                    self.shapes_graph.add((property_shape_uri, RDF.type, SH.PropertyShape))
                    self.shapes_graph.add((property_shape_uri, SH.path, URIRef(prop["property"])))
                    self.shapes_graph.add(
                        (property_shape_uri, SH.nodeKind, SH.Literal if prop["data"] else SH.IRI)
                    )
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
                    self.shapes_graph.add((property_shape_uri, SH.name, Literal(name, lang="en")))
                    self.shapes_graph.add(
                        (property_shape_uri, RDFS.label, Literal(name, lang="en"))
                    )
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
        }}
        """
        setup_cmempy_user_access(self.context.user)
        post_update(query)

    def post_provenance(self) -> None:
        """Post provenance"""
        prov = self.get_provenance()
        if prov:
            param_sparql = ""
            for name, iri in prov["parameters"].items():
                param_sparql += f'\n<{prov["plugin_iri"]}> <{iri}> "{self.__dict__[name]}" .'
            insert_query = f"""
                INSERT DATA {{
                    GRAPH <{self.shapes_graph_iri}> {{
                        <{self.shapes_graph_iri}> <http://purl.org/dc/terms/creator>
                            <{prov["plugin_iri"]}> .
                        <{prov["plugin_iri"]}> a <{prov["plugin_type"]}>,
                            <https://vocab.eccenca.com/di/CustomTask> .
                        <{prov["plugin_iri"]}> <http://www.w3.org/2000/01/rdf-schema#label>
                            "{prov["plugin_label"]}" .
                        {param_sparql}
                    }}
                }}
            """
            post_update(query=insert_query)

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
            }}
        """

        result = json.loads(post_sparql(query=type_query))

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
            }}
        """

        new_plugin_iri = f"{'_'.join(plugin_iri.split('_')[:-1])}_{token_hex(8)}"
        label = f"{self.label} plugin"
        result = json.loads(post_sparql(query=parameter_query))

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

    def create_graph(self) -> None:
        """Create or replace SHACL shapes graph"""
        self.create_label()
        post_streamed(
            self.shapes_graph_iri,
            BytesIO(self.shapes_graph.serialize(format="nt", encoding="utf-8")),
            replace=self.replace,
            content_type="application/n-triples",
        )
        now = datetime.now(UTC).isoformat(timespec="milliseconds")[:-6] + "Z"
        query_add_created = f"""
            PREFIX dcterms: <http://purl.org/dc/terms/>
            PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
            INSERT DATA {{
                GRAPH <{self.shapes_graph_iri}> {{
                    <{self.shapes_graph_iri}> dcterms:created "{now}"^^xsd:dateTime
                }}
            }}
        """
        post_update(query_add_created)

    def create_label(self, label: str = "") -> None:
        """Create label in shapes graph"""
        if not label:
            label = f"Shapes for: {self.data_graph_iri}"
        self.shapes_graph.add(
            (
                URIRef(self.shapes_graph_iri),
                RDFS.label,
                Literal(label),
            )
        )

    def backup_label(self, label) -> None:
        """Store previous malformed label with rdfs:comment in shapes graph"""
        self.shapes_graph.add(
            (
                URIRef(self.shapes_graph_iri),
                RDFS.comment,
                Literal(f"Previous label: {label}"),
            )
        )

    def remove_label(self, label: str) -> None:
        """Remove label from shapes graph"""
        query = f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        DELETE DATA {{
            GRAPH <{self.shapes_graph_iri}> {{
                <{self.shapes_graph_iri}> rdfs:label "{label}"
            }}
        }}
        """
        post_update(query=query)

    def add_to_label(self) -> None:
        """Add source graph to label"""
        shapes_graph_metadata = next(
            _ for _ in self.graphs_list if _["iri"] == self.shapes_graph_iri
        )
        if "label" not in shapes_graph_metadata or "title" not in shapes_graph_metadata["label"]:
            self.log.warning("No label in existing shapes graph.")
            return self.create_label()
        label: str = shapes_graph_metadata["label"]["title"]
        if not label:
            self.log.warning("No label in existing shapes graph.")
            return self.create_label()
        source_graphs = label.split("Shapes for: ")[-1].split(", ")
        if self.data_graph_iri in source_graphs:
            return None
        self.remove_label(label)
        if {validators.url(_) for _ in source_graphs} != {True} or not label.startswith(
            "Shapes for: "
        ):
            self.log.warning("Malformed label in existing shapes graph.")
            self.backup_label(label)
            return self.create_label()
        return self.create_label(label=f"{label}, {self.data_graph_iri}")

    def add_to_graph(self) -> None:
        """Add SHACL shapes to existing graph"""
        self.add_to_label()
        query_data = f"""
        INSERT DATA {{
            GRAPH <{self.shapes_graph_iri}> {{
                {self.shapes_graph.serialize(format="nt", encoding="utf-8").decode()}
            }}
        }}"""
        post_update(query_data)

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
        }}
        """
        setup_cmempy_user_access(self.context.user)
        post_update(query_remove_modified)

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
        }}
        """  # noqa: S608
        post_update(query_add_modified)

    def update_execution_report(self) -> None:
        """Update execution report"""
        self.context.report.update(
            ExecutionReport(
                entity_count=self.shapes_count,
                operation="write",
                operation_desc="shapes created",
            )
        )

    def execute(self, inputs: Sequence[Entities], context: ExecutionContext) -> None:  # noqa: ARG002
        """Execute plugin"""
        self.context = context
        self.update_execution_report()
        setup_cmempy_user_access(context.user)
        graph_exists = self.shapes_graph_iri in [_["iri"] for _ in get_graphs_list()]
        if self.existing_graph == "stop" and graph_exists:
            raise ValueError(f"Graph <{self.shapes_graph_iri}> already exists.")

        self.prefixes = self.get_prefixes()
        self.shapes_graph = self.init_shapes_graph()
        self.dp_api_endpoint = get_dp_api_endpoint()
        self.create_shapes()

        setup_cmempy_user_access(context.user)
        if self.existing_graph != "add":
            self.create_graph()
        else:
            self.graphs_list = get_graphs_list()
            if self.shapes_graph_iri in [_["iri"] for _ in self.graphs_list]:
                self.add_to_graph()
            else:
                self.create_graph()
        self.update_execution_report()
        if self.plugin_provenance:
            self.post_provenance()
        if self.import_shapes:
            self.import_shapes_graph()
