"""Generate SHACL node and property shapes from a data graph"""

from io import BytesIO
from json import load, loads
from os import environ
from pathlib import Path
from urllib.parse import quote_plus
from urllib.request import urlopen
from uuid import NAMESPACE_URL, uuid5

from cmem.cmempy.api import send_request
from cmem.cmempy.config import get_dp_api_endpoint
from cmem.cmempy.dp.proxy.graph import get_graphs_list, post_streamed
from cmem.cmempy.dp.proxy.sparql import get
from cmem.cmempy.dp.proxy.update import post
from cmem.cmempy.workspace.projects.project import get_prefixes
from cmem_plugin_base.dataintegration.context import ExecutionContext
from cmem_plugin_base.dataintegration.description import Icon, Plugin, PluginParameter
from cmem_plugin_base.dataintegration.plugins import WorkflowPlugin
from cmem_plugin_base.dataintegration.types import (
    BoolParameterType,
    StringParameterType,
)
from cmem_plugin_base.dataintegration.utils import setup_cmempy_user_access
from rdflib import RDF, RDFS, SH, XSD, Graph, Literal, Namespace, URIRef
from rdflib.namespace import split_uri
from str2bool import str2bool
from validators import url

from cmem_plugin_shapes.parameter_types import GraphParameterTypeNew

from . import __path__

SHUI = Namespace("https://vocab.eccenca.com/shui/")

environ["SSL_VERIFY"] = "false"


def format_namespace(iri: str) -> str:
    """Add '/' to namespace if graph IRI does not end with '/' or '#'"""
    return iri if iri.endswith(("/", "#")) else iri + "/"


@Plugin(
    label="Generate SHACL shapes from data",
    icon=Icon(file_name="shacl.jpg", package=__package__),
    description="Generates SHACL node and property shapes from a data graph",
    documentation="",
    parameters=[
        PluginParameter(
            param_type=GraphParameterTypeNew(),
            name="data_graph_iri",
            label="Input data graph.",
            description="",
        ),
        PluginParameter(
            param_type=StringParameterType(),
            name="shapes_graph_iri",
            label="Output SHACL shapes graph.",
            description="",
        ),
        PluginParameter(
            param_type=BoolParameterType(),
            name="overwrite",
            label="Overwrite shapes graph if it exists.",
            description="",
            default_value=False,
        ),
        PluginParameter(
            param_type=BoolParameterType(),
            name="import_shapes",
            label="Import shapes graph in CMEM Shapes Catalog.",
            description="",
            default_value=False,
        ),
    ],
)
class ShapesPlugin(WorkflowPlugin):
    """SHACL shapes EasyNav plugin"""

    def __init__(
        self,
        data_graph_iri: str = "",
        shapes_graph_iri: str = "",
        overwrite: bool = False,
        import_shapes: bool = False,
    ) -> None:
        if not url(shapes_graph_iri):
            raise ValueError("shapes graph IRI parameter is invalid")
        self.shapes_graph_iri = shapes_graph_iri
        self.data_graph_iri = data_graph_iri
        self.overwrite = overwrite
        self.import_shapes = import_shapes

        self.dp_api_endpoint = get_dp_api_endpoint()

    def get_prefixes(self) -> dict:
        """Get list of prefixes from prefix.cc or use local copy"""
        prefixes = {}
        err = None
        try:
            res = urlopen("http://prefix.cc/popular/all.file.json")
            if res.status == 200:  # noqa: PLR2004
                self.log.info("prefixes fetched from http://prefix.cc")
                prefixes = {v: k for k, v in loads(res.read()).items()}
            else:
                err = res.status
        except Exception as exc:  # noqa: BLE001
            err = exc
        if err:
            self.log.warning(
                f"failed to fetch prefixes from http://prefix.cc ({err}) - using local file"
            )
            with (Path(__path__[0]) / "prefix.cc.json").open("r") as json_file:
                prefixes = {v: k for k, v in load(json_file).items()}
        prefixes_project = {v: k for k, v in get_prefixes(self.context.task.project_id()).items()}
        prefixes.update(prefixes_project)
        return prefixes

    def get_name(self, iri: str) -> str:
        """Get shape name."""
        url = f"{self.dp_api_endpoint}/api/explore/title?resource={quote_plus(iri)}"
        response = send_request(
            url,
            method="GET",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        title_json = loads(response)
        title: str = title_json["title"]
        try:
            namespace, resource = split_uri(iri)
        except ValueError:
            namespace = iri
        if namespace in self.prefixes:
            title += f" ({self.prefixes[namespace]}:)"
        return title

    def init_shapes_graph(self) -> Graph:
        """Return initial shapes graph"""
        shapes_graph_uri = URIRef(self.shapes_graph_iri)
        shapes_graph = Graph()
        shapes_graph.add((shapes_graph_uri, RDF.type, SHUI.ShapeCatalog))
        shapes_graph.add(
            (shapes_graph_uri, RDFS.label, Literal(f"Shapes for {self.data_graph_iri}"))
        )
        return shapes_graph

    def get_class_dict(self) -> dict:
        """Get classes and properties"""
        setup_cmempy_user_access(self.context.user)
        class_dict: dict = {}
        query = f"""
            SELECT DISTINCT ?class ?property ?data ?inverse
            FROM <{self.data_graph_iri}> {{
                {{
                    ?subject a ?class .
                    ?subject ?property ?object
                    BIND(isLiteral(?object) AS ?data)
                    BIND("false" AS ?inverse)
                }}
            UNION
                {{
                    ?object a ?class .
                    ?subject ?property ?object
                    BIND("false" AS ?data)
                    BIND("true" AS ?inverse)
                }}
            }}
        """  # noqa: S608
        res = loads(get(query))
        for binding in res["results"]["bindings"]:
            if binding["class"]["value"] not in class_dict:
                class_dict[binding["class"]["value"]] = []
            class_dict[binding["class"]["value"]].append(
                {
                    "property": binding["property"]["value"],
                    "data": str2bool(binding["data"]["value"]),
                    "inverse": str2bool(binding["inverse"]["value"]),
                }
            )
        return class_dict

    def make_shapes(self, shapes_graph: Graph) -> Graph:
        """Make shapes"""
        prop_uuids = []
        class_dict = self.get_class_dict()
        for cls, props in class_dict.items():
            node_shape_uri = URIRef(
                f"{format_namespace(self.shapes_graph_iri)}{uuid5(NAMESPACE_URL, cls)}"
            )
            shapes_graph.add((node_shape_uri, RDF.type, SH.NodeShape))
            shapes_graph.add((node_shape_uri, SH.targetClass, URIRef(cls)))
            name = self.get_name(cls)
            shapes_graph.add((node_shape_uri, SH.name, Literal(name, lang="en")))
            shapes_graph.add((node_shape_uri, RDFS.label, Literal(name, lang="en")))
            for prop in props:
                if prop["inverse"]:
                    prop_uuid = uuid5(NAMESPACE_URL, f'{prop["property"]}inverse')
                else:
                    prop_uuid = uuid5(NAMESPACE_URL, prop["property"])
                property_shape_uri = URIRef(f"{format_namespace(self.shapes_graph_iri)}{prop_uuid}")
                if prop_uuid not in prop_uuids:
                    name = self.get_name(prop["property"])
                    shapes_graph.add((property_shape_uri, RDF.type, SH.PropertyShape))
                    shapes_graph.add((property_shape_uri, SH.path, URIRef(prop["property"])))
                    if prop["data"]:
                        shapes_graph.add((property_shape_uri, SH.nodeKind, SH.Literal))
                    else:
                        shapes_graph.add((property_shape_uri, SH.nodeKind, SH.IRI))
                        if prop["inverse"]:
                            shapes_graph.add(
                                (
                                    property_shape_uri,
                                    SHUI.inversePath,
                                    Literal("true", datatype=XSD.boolean),
                                )
                            )
                            name = "← " + name
                    shapes_graph.add((property_shape_uri, SH.name, Literal(name, lang="en")))
                    shapes_graph.add((property_shape_uri, RDFS.label, Literal(name, lang="en")))
                    prop_uuids.append(prop_uuid)
                shapes_graph.add((node_shape_uri, SH.property, property_shape_uri))
        return shapes_graph

    def import_shapes_graph(self) -> None:
        """Add shapes IRI to owl:imports in CMEM Shapes Catalog"""
        query = f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        INSERT DATA {{
            GRAPH <https://vocab.eccenca.com/shacl/> {{
                <https://vocab.eccenca.com/shacl/> owl:imports
                    <{self.shapes_graph_iri}> .
            }}
        }}
        """
        setup_cmempy_user_access(self.context.user)
        post(query)

    def execute(self, inputs: tuple, context: ExecutionContext) -> None:  # noqa: ARG002
        """Execute plugin"""
        self.context = context
        setup_cmempy_user_access(context.user)
        self.prefixes: dict[str, str] = self.get_prefixes()
        if not self.overwrite and self.shapes_graph_iri in [i["iri"] for i in get_graphs_list()]:
            raise ValueError(f"Graph <{self.shapes_graph_iri}> already exists")
        shapes_graph = self.init_shapes_graph()
        shapes_graph = self.make_shapes(shapes_graph)
        nt_file = BytesIO(shapes_graph.serialize(format="nt", encoding="utf-8"))
        res = post_streamed(
            self.shapes_graph_iri,
            nt_file,
            replace=self.overwrite,
            content_type="application/n-triples",
        )
        if res.status_code != 204:  # noqa: PLR2004
            raise OSError(f"Error posting SHACL validation graph (status code {res.status_code}).")
        if self.import_shapes:
            self.import_shapes_graph()
