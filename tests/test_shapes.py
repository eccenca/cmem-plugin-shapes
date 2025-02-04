"""Plugin tests."""

import json
import os
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from cmem.cmempy.dp.proxy.graph import get
from cmem.cmempy.dp.proxy.sparql import get as ask
from rdflib import Graph
from rdflib.compare import isomorphic

from cmem_plugin_shapes.plugin_shapes import ShapesPlugin
from tests import FIXTURE_DIR
from tests.cmemc_command_utils import run, run_without_assertion
from tests.utils import TestExecutionContext


@dataclass
class GraphSetupFixture:
    """Graph Setup Fixture"""

    project_name: str = "shapes_plugin_test"
    shapes_iri: str = "http://docker.localhost/my-persons-shapes"
    shapes_file: str = str(FIXTURE_DIR / "test_shapes.ttl")
    dataset_iri: str = "http://docker.localhost/my-persons"
    dataset_file: str = str(FIXTURE_DIR / "test_shapes_data.ttl")
    dataset_file_add: str = str(FIXTURE_DIR / "test_shapes_data_add.ttl")
    catalog_iri: str = "https://vocab.eccenca.com/shacl/"
    catalog_file: str = str(FIXTURE_DIR / "test_shapes_eccenca.ttl")
    ask_query: str = """PREFIX owl: <http://www.w3.org/2002/07/owl#>
ASK
{
  GRAPH <https://vocab.eccenca.com/shacl/> {
    <https://vocab.eccenca.com/shacl/> owl:imports <http://docker.localhost/my-persons-shapes>
  }
}"""


@pytest.fixture
def graph_setup(tmp_path: Path, add: bool = False) -> Generator[GraphSetupFixture, Any, None]:
    """Graph setup fixture"""
    if os.environ.get("CMEM_BASE_URI", "") == "":
        pytest.skip("Needs CMEM configuration")
    # make backup and delete all GRAPHS
    _ = GraphSetupFixture()
    export_zip = str(tmp_path / "export.store.zip")
    run(["admin", "store", "export", export_zip])
    if add:
        run(["graph", "import", _.dataset_file_add, _.dataset_iri])
    else:
        run(["graph", "import", _.dataset_file, _.dataset_iri])
    run(["graph", "import", _.dataset_file, _.dataset_iri])
    run_without_assertion(["project", "delete", _.project_name])
    run(["project", "create", _.project_name])
    yield _
    # remove test GRAPHS
    run(["admin", "store", "import", export_zip])


def test_setup(graph_setup: GraphSetupFixture) -> None:
    """Test plugin execution"""
    _ = graph_setup


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
    result_graph = Graph().parse(data=result_graph_turtle)
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


@pytest.mark.parametrize("add", [(True)])
def test_workflow_execution_add(graph_setup: GraphSetupFixture, add: bool) -> None:  # noqa: ARG001
    """Test plugin execution with "add to graph" setting"""
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
    test = Graph().parse(f"{FIXTURE_DIR}/test_shapes.ttl")
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
    assert not json.loads(ask(query=graph_setup.ask_query)).get("boolean", True)
    ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph="replace",
        import_shapes=True,
        prefix_cc=False,
    ).execute(inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name))
    assert json.loads(ask(query=graph_setup.ask_query)).get("boolean", False)


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
