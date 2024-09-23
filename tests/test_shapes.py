"""Plugin tests."""

from contextlib import suppress
from pathlib import Path

import pytest
from cmem.cmempy.dp.proxy.graph import delete, get, post
from cmem.cmempy.dp.proxy.update import post as post_update
from cmem.cmempy.workspace.projects.project import delete_project, make_new_project
from rdflib import Graph
from rdflib.compare import to_isomorphic

from cmem_plugin_shapes.plugin_shapes import ShapesPlugin
from tests.utils import TestExecutionContext, needs_cmem

from . import __path__

UUID = "5072e1e3e96c40389116a6833d9a3867"
PROJECT_NAME = f"shapes_plugin_test_{UUID}"
RESULT_IRI = f"https://eccenca.com/shapes_plugin/{UUID}/shapes/"
DATA_IRI = f"https://eccenca.com/shapes_plugin/{UUID}/data/"


@pytest.fixture
def _setup(request: pytest.FixtureRequest) -> None:
    """Create DI project"""

    def remove_import() -> None:
        query = f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        DELETE DATA {{
            GRAPH <https://vocab.eccenca.com/shacl/> {{
                <https://vocab.eccenca.com/shacl/> owl:imports <{RESULT_IRI}> .
            }}
        }}
        """
        post_update(query=query)

    with suppress(Exception):
        delete_project(PROJECT_NAME)
    make_new_project(PROJECT_NAME)

    res = post(DATA_IRI, Path(__path__[0]) / "test_shapes_data.ttl", replace=False)
    if res.status_code != 204:  # noqa: PLR2004
        raise ValueError(f"Response {res.status_code}: {res.url}")

    request.addfinalizer(lambda: delete_project(PROJECT_NAME))
    request.addfinalizer(lambda: remove_import)
    request.addfinalizer(lambda: delete(DATA_IRI))
    request.addfinalizer(lambda: delete(RESULT_IRI))  # noqa: PT021


@needs_cmem
def test_workflow_execution(_setup: pytest.FixtureRequest) -> None:  # noqa: PT019
    """Test plugin execution"""
    ShapesPlugin(
        data_graph_iri=DATA_IRI,
        shapes_graph_iri=RESULT_IRI,
        overwrite=False,
        import_shapes=True,
    ).execute(inputs=None, context=TestExecutionContext(project_id=PROJECT_NAME))

    result = Graph().parse(data=get(RESULT_IRI, owl_imports_resolution=False).text)
    test = Graph().parse(Path(__path__[0]) / "test_shapes.ttl", format="turtle")
    assert to_isomorphic(result) == to_isomorphic(test)
