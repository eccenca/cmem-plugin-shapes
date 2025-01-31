"""Plugin tests."""

import json
from collections.abc import Generator
from pathlib import Path
from shutil import rmtree
from tempfile import mkdtemp

import pytest
from cmem.cmempy.dp.proxy.graph import get
from cmem.cmempy.dp.proxy.sparql import get as ask
from rdflib import Graph
from rdflib.compare import isomorphic

from cmem_plugin_shapes.plugin_shapes import ShapesPlugin
from tests.utils import TestExecutionContext, needs_cmem

from .cmemc_command_utils import run, run_without_assertion

FIXTURE_DIR = str(Path(__file__).parent / "fixture_dir")

UUID = "5072e1e3e96c40389116a6833d9a3867"
PROJECT_NAME = f"shapes_plugin_test_{UUID}"


GRAPHS = {
    "shapes": {
        "location": f"{FIXTURE_DIR}/test_shapes.ttl",
        "iri": "http://docker.localhost/my-persons-shapes",
    },
    "dataset": {
        "location": f"{FIXTURE_DIR}/test_shapes_data.ttl",
        "iri": "http://docker.localhost/my-persons",
    },
}

ECCENCA_SHAPES_CATELOG = {
    "location": f"{FIXTURE_DIR}/test_shapes_eccenca.ttl",
    "iri": "https://vocab.eccenca.com/shacl/",
}

ASK_QUERY = """PREFIX owl: <http://www.w3.org/2002/07/owl#>
ASK
{
  GRAPH <https://vocab.eccenca.com/shacl/> {
    <https://vocab.eccenca.com/shacl/> owl:imports <http://docker.localhost/my-persons-shapes>
  }
}"""


@pytest.fixture
def graph_setup() -> Generator[None, None, None]:
    """Graph setup fixture"""
    # make backup and delete all GRAPHS
    backup_directory = mkdtemp(prefix="cmemc-GRAPHS-backup")
    run(["graph", "export", "--all", "--output-dir", backup_directory])
    run(["graph", "delete", "--all"])
    run(["graph", "import", GRAPHS["dataset"]["location"], GRAPHS["dataset"]["iri"]])
    run_without_assertion(["project", "delete", PROJECT_NAME])
    run(["project", "create", PROJECT_NAME])
    yield None
    # remove test GRAPHS
    for _ in GRAPHS.values():
        run(["graph", "delete", _["iri"]])

    # import backup GRAPHS and compare triple counts
    run(["graph", "import", backup_directory])
    rmtree(backup_directory)


@needs_cmem
@pytest.mark.usefixtures("graph_setup")
def test_workflow_execution() -> None:
    """Test plugin execution"""
    data_graph_iri = GRAPHS["dataset"]["iri"]
    shapes_graph_iri = GRAPHS["shapes"]["iri"]
    ShapesPlugin(
        data_graph_iri=data_graph_iri,
        shapes_graph_iri=shapes_graph_iri,
        overwrite=True,
        import_shapes=False,
        prefix_cc=False,
    ).execute(inputs=[], context=TestExecutionContext(project_id=PROJECT_NAME))
    result_graph = Graph().parse(data=get(shapes_graph_iri, owl_imports_resolution=False).text)
    test = Graph().parse(f"{FIXTURE_DIR}/test_shapes.ttl")
    assert isomorphic(result_graph, test)
    with pytest.raises(
        ValueError, match="Graph <http://docker.localhost/my-persons-shapes> already exists."
    ):
        ShapesPlugin(
            data_graph_iri=data_graph_iri,
            shapes_graph_iri=shapes_graph_iri,
            overwrite=False,
            import_shapes=False,
            prefix_cc=False,
        ).execute(inputs=[], context=TestExecutionContext(project_id=PROJECT_NAME))


@needs_cmem
@pytest.mark.usefixtures("graph_setup")
def test_import_shapes() -> None:
    """Test plugin execution with import shapes"""
    data_graph_iri = GRAPHS["dataset"]["iri"]
    shapes_graph_iri = GRAPHS["shapes"]["iri"]
    ShapesPlugin(
        data_graph_iri=data_graph_iri,
        shapes_graph_iri=shapes_graph_iri,
        overwrite=True,
        import_shapes=False,
        prefix_cc=False,
    ).execute(inputs=[], context=TestExecutionContext(project_id=PROJECT_NAME))
    assert not json.loads(ask(query=ASK_QUERY)).get("boolean", True)
    ShapesPlugin(
        data_graph_iri=data_graph_iri,
        shapes_graph_iri=shapes_graph_iri,
        overwrite=True,
        import_shapes=True,
        prefix_cc=False,
    ).execute(inputs=[], context=TestExecutionContext(project_id=PROJECT_NAME))
    assert json.loads(ask(query=ASK_QUERY)).get("boolean", False)
