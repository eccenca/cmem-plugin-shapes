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
from cmem.cmempy.dp.proxy.sparql import get as sparql_get
from cmem.cmempy.dp.proxy.update import post
from cmem_plugin_base.testing import TestExecutionContext
from rdflib import DCTERMS, Graph, URIRef
from rdflib.compare import isomorphic

from cmem_plugin_shapes.plugin_shapes import (
    EXISTING_GRAPH_ADD,
    EXISTING_GRAPH_REPLACE,
    EXISTING_GRAPH_STOP,
    ShapesPlugin,
)
from tests import FIXTURE_DIR
from tests.cmemc_command_utils import run, run_without_assertion

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
    ask_query: str = """
    PREFIX owl: <http://www.w3.org/2002/07/owl#>
    ASK {
      GRAPH <https://vocab.eccenca.com/shacl/> {
        <https://vocab.eccenca.com/shacl/> owl:imports <http://docker.localhost/my-persons-shapes>
      }
    }"""
    label_query: str = f"""
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    SELECT ?label {{
        GRAPH <{shapes_iri}> {{
            <{shapes_iri}> rdfs:label ?label
            FILTER(LANG(?label) = "en")
        }}
    }}"""
    remove_label_query: str = f"""
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    DELETE {{
        GRAPH <{shapes_iri}> {{
            <{shapes_iri}> rdfs:label ?label
        }}
    }}
    WHERE {{
        GRAPH <{shapes_iri}> {{
            <{shapes_iri}> rdfs:label ?label
        }}
    }}"""


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
    export_zip = str(tmp_path / "export.store.zip")
    run(["admin", "store", "export", export_zip])
    run(["graph", "import", "--replace", _.dataset_file, _.dataset_iri])
    if add_to_graph:
        run(["graph", "import", "--replace", _.shapes_file_add_init, _.shapes_iri])
    run_without_assertion(["project", "delete", _.project_name])
    run(["project", "create", _.project_name])
    yield _
    # remove test GRAPHS
    run(["admin", "store", "import", export_zip])


def test_workflow_execution(graph_setup: GraphSetupFixture) -> None:
    """Test plugin execution"""
    plugin = ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph=EXISTING_GRAPH_REPLACE,
        import_shapes=False,
        prefix_cc=False,
        plugin_provenance=True,
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
            existing_graph=EXISTING_GRAPH_STOP,
            import_shapes=False,
            prefix_cc=False,
        ).execute(inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name))


def test_workflow_execution_add_graph_not_exists(graph_setup: GraphSetupFixture) -> None:
    """Test plugin execution with "add to graph" setting without existing graph"""
    plugin = ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph=EXISTING_GRAPH_ADD,
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
        existing_graph=EXISTING_GRAPH_ADD,
        import_shapes=False,
        prefix_cc=False,
        label="New label",
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


def test_additional_inits() -> None:
    """Test addition inits"""
    iri1 = "http://example.com/1"
    iri2 = "http://example.com/2"

    try:
        ShapesPlugin(data_graph_iri=iri1, shapes_graph_iri=iri2, ignore_properties="")
    except ValueError:
        pytest.fail("Usage with empty ignore_properties list should not fail.")


def test_failing_inits() -> None:
    """Test failing inits"""
    iri1 = "http://example.com/1"
    iri2 = "http://example.com/2"
    with pytest.raises(ValueError, match="Invalid value for parameter 'Input data graph'"):
        ShapesPlugin(
            data_graph_iri="no iri",
            shapes_graph_iri=iri1,
        )
    with pytest.raises(ValueError, match="Invalid value for parameter 'Output shape catalog'"):
        ShapesPlugin(
            data_graph_iri=iri1,
            shapes_graph_iri="no iri",
        )
    with pytest.raises(ValueError, match="Shapes graph IRI cannot be the same as data graph IRI"):
        ShapesPlugin(
            data_graph_iri=iri1,
            shapes_graph_iri=iri1,
        )
    with pytest.raises(ValueError, match="Invalid value for parameter 'Handle existing output"):
        ShapesPlugin(
            data_graph_iri=iri1,
            shapes_graph_iri=iri2,
            existing_graph="invalid",
        )
    with pytest.raises(ValueError, match="Invalid property IRI"):
        ShapesPlugin(
            data_graph_iri=iri1,
            shapes_graph_iri=iri2,
            ignore_properties="""no iri""",
        )
    with pytest.raises(ValueError, match="Invalid property IRI"):
        ShapesPlugin(
            data_graph_iri=iri1,
            shapes_graph_iri=iri2,
            ignore_properties="""http://www.w3.org/1999/02/22-rdf-syntax-ns#type
            no iri""",
        )
    with pytest.raises(ValueError, match="Invalid value for parameter"):
        ShapesPlugin(
            data_graph_iri=iri1,
            shapes_graph_iri=iri2,
            existing_graph="unknown",
        )


def test_prefix_cc_fetching(graph_setup: GraphSetupFixture) -> None:
    """Test prefix.cc fetching"""
    plugin = ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph=EXISTING_GRAPH_REPLACE,
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
        existing_graph=EXISTING_GRAPH_REPLACE,
        import_shapes=False,
        prefix_cc=False,
    ).execute(inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name))
    assert not json.loads(sparql_get(query=graph_setup.ask_query)).get("boolean", True)
    ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph=EXISTING_GRAPH_REPLACE,
        import_shapes=True,
        prefix_cc=False,
    ).execute(inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name))
    assert json.loads(sparql_get(query=graph_setup.ask_query)).get("boolean", False)


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
        ShapesPlugin.iri_list_to_filter(iris=[rdf_type, rdfs_label], filter_="XX")


@pytest.mark.parametrize("add_to_graph", [True])
def test_add_to_graph_label(graph_setup: GraphSetupFixture, add_to_graph: bool) -> None:
    """Test add to label"""
    assert graph_setup.add_to_graph == add_to_graph
    plugin = ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph=EXISTING_GRAPH_ADD,
        import_shapes=False,
        prefix_cc=False,
        label="",
    )
    plugin.context = TestExecutionContext()

    plugin.shapes_graph = Graph()
    plugin.add_to_graph()
    bindings = json.loads(sparql_get(query=graph_setup.label_query))["results"]["bindings"]
    assert len(bindings) == 1
    assert bindings[0]["label"]["value"] == f"Shapes for {graph_setup.dataset_iri}"

    post(query=graph_setup.remove_label_query)
    plugin.shapes_graph = Graph()
    plugin.add_to_graph()
    bindings = json.loads(sparql_get(query=graph_setup.label_query))["results"]["bindings"]
    assert len(bindings) == 1
    assert bindings[0]["label"]["value"] == f"Shapes for {graph_setup.dataset_iri}"

    post(query=graph_setup.remove_label_query)
    query = f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        INSERT DATA {{
            GRAPH <{graph_setup.shapes_iri}> {{
                <{graph_setup.shapes_iri}> rdfs:label "test label"@de
            }}
        }}"""
    post(query=query)
    plugin.shapes_graph = Graph()
    plugin.add_to_graph()
    bindings = json.loads(sparql_get(query=graph_setup.label_query))["results"]["bindings"]
    assert len(bindings) == 1
    assert bindings[0]["label"]["value"] == f"Shapes for {graph_setup.dataset_iri}"

    plugin.label = "New label"

    plugin.shapes_graph = Graph()
    plugin.add_to_graph()
    bindings = json.loads(sparql_get(query=graph_setup.label_query))["results"]["bindings"]
    assert len(bindings) == 1
    assert bindings[0]["label"]["value"] == "New label"

    post(query=graph_setup.remove_label_query)
    plugin.shapes_graph = Graph()
    plugin.add_to_graph()
    bindings = json.loads(sparql_get(query=graph_setup.label_query))["results"]["bindings"]
    assert len(bindings) == 1
    assert bindings[0]["label"]["value"] == "New label"
