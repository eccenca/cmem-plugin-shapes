"""Plugin tests."""

import json
import os
import re
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from cmem.cmempy.dp.proxy.graph import get
from cmem.cmempy.dp.proxy.sparql import get as get_sparql
from rdflib import DCTERMS, RDFS, Graph, Literal, URIRef
from rdflib.compare import isomorphic

from cmem_plugin_shapes.plugin_shapes import ShapesPlugin
from tests import FIXTURE_DIR
from tests.cmemc_command_utils import run, run_without_assertion
from tests.utils import TestExecutionContext

DATETIME_PATTERN = re.compile(
    r'^"[1-9][0-9]{3}-[0-1][1-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9].[0-9]{3}Z"\^\^'
    "<http://www.w3.org/2001/XMLSchema#dateTime>"
)


@dataclass
class GraphSetupFixture:
    """Graph Setup Fixture"""

    add_to_graph: bool = True
    project_name: str = "shapes_plugin_test"
    shapes_iri: str = "http://docker.localhost/my-persons-shapes"
    shapes_file: str = str(FIXTURE_DIR / "test_shapes.ttl")
    shapes_file_add_init: str = str(FIXTURE_DIR / "test_shapes_add_init.ttl")
    dataset_iri: str = "http://docker.localhost/my-persons"
    dataset_file: str = str(FIXTURE_DIR / "test_shapes_data.ttl")
    catalog_iri: str = "https://vocab.eccenca.com/shacl/"
    catalog_file: str = str(FIXTURE_DIR / "test_shapes_eccenca.ttl")
    label: str = f"Shapes for: {dataset_iri}"
    ask_query: str = """PREFIX owl: <http://www.w3.org/2002/07/owl#>
ASK
{
  GRAPH <https://vocab.eccenca.com/shacl/> {
    <https://vocab.eccenca.com/shacl/> owl:imports <http://docker.localhost/my-persons-shapes>
  }
}"""


@pytest.fixture
def add_to_graph() -> bool:
    """Add to graph parameter fixture

    this parameter is used to allow different graph_setup fixtures
    """
    return False


@pytest.fixture
def graph_setup(tmp_path: Path, add_to_graph: bool) -> Generator[GraphSetupFixture, Any, None]:
    """Graph setup fixture"""
    if os.environ.get("CMEM_BASE_URI", "") == "":
        pytest.skip("Needs CMEM configuration")
    # make backup and delete all GRAPHS
    _ = GraphSetupFixture()
    _.add_to_graph = add_to_graph
    export_zip = str(tmp_path / "export.store.zip")
    run(["admin", "store", "export", export_zip])
    run(["graph", "import", _.dataset_file, _.dataset_iri])
    if add_to_graph:
        run(["graph", "import", _.shapes_file_add_init, _.shapes_iri])
    run_without_assertion(["project", "delete", _.project_name])
    run(["project", "create", _.project_name])
    yield _
    # remove test GRAPHS
    run(["admin", "store", "import", export_zip])


@pytest.fixture
def graph_setup_label() -> GraphSetupFixture:
    """Graph setup fixture for add-to-label tests"""
    return GraphSetupFixture()


def test_workflow_execution(graph_setup: GraphSetupFixture) -> None:
    """Test plugin execution"""
    plugin = ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph="replace",
        import_shapes=False,
        prefix_cc=False,
    )
    plugin.execute(inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name))
    result_graph_turtle = get(graph_setup.shapes_iri, owl_imports_resolution=False).text
    regexp = rf"<{graph_setup.shapes_iri}> <http://purl.org/dc/terms/created> .* \."
    created = re.findall(regexp, result_graph_turtle)
    assert len(created) == 1
    datetime = created[0].split()[-2]
    assert DATETIME_PATTERN.match(datetime)
    result_graph = Graph().parse(data=result_graph_turtle)
    assert len(list(result_graph.objects(predicate=DCTERMS.modified))) == 0
    result_graph.remove((URIRef(graph_setup.shapes_iri), DCTERMS.created, None))
    test = Graph().parse(f"{FIXTURE_DIR}/test_shapes.ttl")
    assert isomorphic(result_graph, test)
    with pytest.raises(
        ValueError, match="Graph <http://docker.localhost/my-persons-shapes> already exists."
    ):
        ShapesPlugin(
            data_graph_iri=graph_setup.dataset_iri,
            shapes_graph_iri=graph_setup.shapes_iri,
            existing_graph="stop",
            import_shapes=False,
            prefix_cc=False,
        ).execute(inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name))


def test_workflow_execution_add_graph_not_exists(graph_setup: GraphSetupFixture) -> None:
    """Test plugin execution with "add to graph" setting without existing graph"""
    plugin = ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph="add",
        import_shapes=False,
        prefix_cc=False,
    )
    plugin.execute(inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name))
    result_graph_turtle = get(graph_setup.shapes_iri, owl_imports_resolution=False).text
    result_graph = Graph().parse(data=result_graph_turtle)
    assert len(list(result_graph.objects(predicate=DCTERMS.created))) == 1
    assert len(list(result_graph.objects(predicate=DCTERMS.modified))) == 0
    result_graph.remove((URIRef(graph_setup.shapes_iri), DCTERMS.created, None))
    test = Graph().parse(f"{FIXTURE_DIR}/test_shapes.ttl")
    test.remove((URIRef(graph_setup.shapes_iri), DCTERMS.modified, None))
    assert isomorphic(result_graph, test)


@pytest.mark.parametrize("add_to_graph", [True])
def test_workflow_execution_add_graph_exists(
    graph_setup: GraphSetupFixture, add_to_graph: bool
) -> None:
    """Test plugin execution with "add to graph" setting with existing graph"""
    plugin = ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph="add",
        import_shapes=False,
        prefix_cc=False,
    )
    assert graph_setup.add_to_graph == add_to_graph
    plugin.execute(inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name))
    result_graph_turtle = get(graph_setup.shapes_iri, owl_imports_resolution=False).text
    regexp = rf"<{graph_setup.shapes_iri}> <http://purl.org/dc/terms/modified> .* \."
    modified = re.findall(regexp, result_graph_turtle)
    assert len(modified) == 1
    datetime = modified[0].split()[-2]
    assert DATETIME_PATTERN.match(datetime)
    result_graph = Graph().parse(data=result_graph_turtle)
    test = Graph().parse(f"{FIXTURE_DIR}/test_shapes_add.ttl")
    assert result_graph.value(
        subject=URIRef(graph_setup.shapes_iri), predicate=DCTERMS.modified
    ) != test.value(subject=URIRef(graph_setup.shapes_iri), predicate=DCTERMS.modified)
    assert len(list(result_graph.objects(predicate=DCTERMS.created))) == 0
    result_graph.remove((URIRef(graph_setup.shapes_iri), DCTERMS.modified, None))
    test.remove((URIRef(graph_setup.shapes_iri), DCTERMS.modified, None))
    assert isomorphic(result_graph, test)


def test_failing_inits(graph_setup: GraphSetupFixture) -> None:
    """Test failing inits"""
    with pytest.raises(ValueError, match="Data graph IRI parameter is invalid"):
        ShapesPlugin(
            data_graph_iri="no iri",
            shapes_graph_iri=graph_setup.shapes_iri,
            existing_graph="stop",
            import_shapes=False,
            prefix_cc=False,
        )
    with pytest.raises(ValueError, match="Shapes graph IRI parameter is invalid"):
        ShapesPlugin(
            data_graph_iri=graph_setup.dataset_iri,
            shapes_graph_iri="no iri",
            existing_graph="stop",
            import_shapes=False,
            prefix_cc=False,
        )
    with pytest.raises(ValueError, match="Ignored property IRI invalid"):
        ShapesPlugin(
            data_graph_iri=graph_setup.dataset_iri,
            shapes_graph_iri=graph_setup.shapes_iri,
            ignore_properties="""no iri""",
        )
    with pytest.raises(ValueError, match="Ignored property IRI invalid"):
        ShapesPlugin(
            data_graph_iri=graph_setup.dataset_iri,
            shapes_graph_iri=graph_setup.shapes_iri,
            ignore_properties="""http://www.w3.org/1999/02/22-rdf-syntax-ns#type
            no iri""",
        )


def test_prefix_cc_fetching(graph_setup: GraphSetupFixture) -> None:
    """Test prefix.cc fetching"""
    plugin = ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph="replace",
        import_shapes=False,
        prefix_cc=True,
    )
    plugin.execute(inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name))
    result_graph_turtle = get(graph_setup.shapes_iri, owl_imports_resolution=False).text
    result_graph = Graph().parse(data=result_graph_turtle)
    result_graph.remove((URIRef(graph_setup.shapes_iri), DCTERMS.created, None))
    test = Graph().parse(f"{FIXTURE_DIR}/test_shapes.ttl")
    assert isomorphic(result_graph, test)


def test_import_shapes(graph_setup: GraphSetupFixture) -> None:
    """Test plugin execution with import shapes"""
    ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph="replace",
        import_shapes=False,
        prefix_cc=False,
    ).execute(inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name))
    assert not json.loads(get_sparql(query=graph_setup.ask_query)).get("boolean", True)
    ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph="replace",
        import_shapes=True,
        prefix_cc=False,
    ).execute(inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name))
    assert json.loads(get_sparql(query=graph_setup.ask_query)).get("boolean", False)


def test_filter_creation() -> None:
    """Test FILTER NOT IN creation"""
    rdf_type = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
    rdfs_label = "http://www.w3.org/2000/01/rdf-schema#label"
    assert (
        ShapesPlugin.iri_list_to_filter(iris=[rdf_type, rdfs_label])
        == f"FILTER (?property NOT IN (<{rdf_type}>, <{rdfs_label}>))"
    )
    assert (
        ShapesPlugin.iri_list_to_filter(iris=[rdfs_label])
        == f"FILTER (?property NOT IN (<{rdfs_label}>))"
    )
    assert ShapesPlugin.iri_list_to_filter(iris=[]) == ""
    assert (
        ShapesPlugin.iri_list_to_filter(iris=[rdf_type, rdfs_label], filter_="IN")
        == f"FILTER (?property IN (<{rdf_type}>, <{rdfs_label}>))"
    )
    assert (
        ShapesPlugin.iri_list_to_filter(iris=[rdf_type, rdfs_label], filter_="IN", name="class")
        == f"FILTER (?class IN (<{rdf_type}>, <{rdfs_label}>))"
    )
    with pytest.raises(ValueError, match="name must match"):
        ShapesPlugin.iri_list_to_filter(iris=[rdf_type, rdfs_label], name="sfsdf sdf")
    with pytest.raises(ValueError, match="filter_ must be"):
        ShapesPlugin.iri_list_to_filter(iris=[rdf_type, rdfs_label], filter_="XXX")


def test_add_to_label(graph_setup_label: GraphSetupFixture) -> None:
    """Test add to label"""
    plugin = ShapesPlugin(
        data_graph_iri=graph_setup_label.dataset_iri,
        shapes_graph_iri=graph_setup_label.shapes_iri,
        existing_graph="add",
        import_shapes=False,
        prefix_cc=False,
    )
    plugin.shapes_graph = Graph()
    invalid_label = "invalid"
    plugin.graphs_list = [
        {
            "iri": graph_setup_label.shapes_iri,
            "label": {"title": invalid_label},
        }
    ]
    ShapesPlugin.add_to_label(plugin)
    labels = list(plugin.shapes_graph.objects(predicate=RDFS.label))
    assert len(labels) == 2  # noqa: PLR2004
    assert Literal(graph_setup_label.label) in labels
    assert Literal(f"Previous label: {invalid_label}") in labels

    plugin.shapes_graph = Graph()
    invalid_label = "Shapes for: invalid"
    plugin.graphs_list = [
        {
            "iri": graph_setup_label.shapes_iri,
            "label": {"title": invalid_label},
        }
    ]
    ShapesPlugin.add_to_label(plugin)
    labels = list(plugin.shapes_graph.objects(predicate=RDFS.label))
    assert len(labels) == 2  # noqa: PLR2004
    assert Literal(graph_setup_label.label) in labels
    assert Literal(f"Previous label: {invalid_label}") in labels

    plugin.shapes_graph = Graph()
    plugin.graphs_list = [
        {
            "iri": graph_setup_label.shapes_iri,
            "label": {"title": graph_setup_label.label},
        }
    ]
    ShapesPlugin.add_to_label(plugin)
    assert list(plugin.shapes_graph.objects(predicate=RDFS.label)) == []

    plugin.shapes_graph = Graph()
    plugin.graphs_list = [{"iri": graph_setup_label.shapes_iri}]
    ShapesPlugin.add_to_label(plugin)
    labels = list(plugin.shapes_graph.objects(predicate=RDFS.label))
    assert labels == [Literal(graph_setup_label.label)]

    plugin.shapes_graph = Graph()
    plugin.graphs_list = [{"iri": graph_setup_label.shapes_iri, "label": {"title": None}}]
    ShapesPlugin.add_to_label(plugin)
    labels = list(plugin.shapes_graph.objects(predicate=RDFS.label))
    assert labels == [Literal(graph_setup_label.label)]
