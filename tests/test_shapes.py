"""Plugin tests."""

from collections.abc import Generator
from contextlib import suppress
from json import loads
from pathlib import Path
from urllib.request import urlopen

import pytest
from cmem.cmempy.dp.proxy.graph import delete, get, post_streamed
from cmem.cmempy.dp.proxy.sparql import post as post_select
from cmem.cmempy.dp.proxy.update import post as post_update
from cmem.cmempy.workspace.projects.project import delete_project, make_new_project
from rdflib import Graph
from rdflib.compare import isomorphic

from cmem_plugin_shapes.plugin_shapes import PREFIX_CC, ShapesPlugin
from tests.utils import TestExecutionContext, needs_cmem

from . import __path__

UUID = "5072e1e3e96c40389116a6833d9a3867"
PROJECT_NAME = f"shapes_plugin_test_{UUID}"
RESULT_IRI = f"https://eccenca.com/shapes_plugin/{UUID}/shapes/"
DATA_IRI = f"https://eccenca.com/shapes_plugin/{UUID}/data/"


@pytest.fixture
def setup() -> Generator:
    """Create DI project"""

    def remove_import() -> None:
        query = f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        DELETE DATA {{
            GRAPH <https://vocab.eccenca.com/shacl/> {{
                <https://vocab.eccenca.com/shacl/> owl:imports <{RESULT_IRI}>
            }}
        }}
        """
        post_update(query=query)

    with suppress(Exception):
        delete_project(PROJECT_NAME)
    make_new_project(PROJECT_NAME)

    res = post_streamed(DATA_IRI, str(Path(__path__[0]) / "test_shapes_data.ttl"), replace=True)
    if res.status_code != 204:  # noqa: PLR2004
        raise ValueError(f"Response {res.status_code}: {res.url}")
    yield None
    delete_project(PROJECT_NAME)
    remove_import()
    delete(DATA_IRI)
    delete(RESULT_IRI)


@needs_cmem
@pytest.mark.usefixtures("setup")
def test_workflow_execution() -> None:
    """Test plugin execution"""
    ShapesPlugin(
        data_graph_iri=DATA_IRI,
        shapes_graph_iri=RESULT_IRI,
        overwrite=True,
        import_shapes=True,
        prefix_cc=False,
    ).execute(inputs=[], context=TestExecutionContext(project_id=PROJECT_NAME))

    query = f"""
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    SELECT ?o {{
        GRAPH <https://vocab.eccenca.com/shacl/> {{
            <https://vocab.eccenca.com/shacl/> owl:imports ?o
        }}
        FILTER( ?o = <{RESULT_IRI}> )
    }}
    """
    result_import = loads(post_select(query=query))
    assert len(result_import["results"]["bindings"]) == 1

    result_graph = Graph().parse(data=get(RESULT_IRI, owl_imports_resolution=False).text)
    test = Graph().parse(Path(__path__[0]) / "test_shapes.ttl", format="turtle")
    assert isomorphic(result_graph, test)
