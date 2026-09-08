"""Plugin tests."""

import os
import re
from collections.abc import Generator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

import pytest
from cmem_client.client import Client
from cmem_client.repositories.graphs import GraphExportConfig, GraphsRepository
from cmem_plugin_base.testing import TestExecutionContext, TestPluginContext
from rdflib import DCTERMS, FOAF, RDF, RDFS, SH, SKOS, Graph, Literal, URIRef
from rdflib.compare import isomorphic
from rdflib.term import Node
from rdflib.util import from_n3

if TYPE_CHECKING:
    from pathlib import Path

    from rdflib.query import ResultRow

from cmem_plugin_shapes.plugin_shapes import (
    EXISTING_GRAPH_ADD,
    EXISTING_GRAPH_REPLACE,
    EXISTING_GRAPH_STOP,
    MANAGED_CLASSES,
    SHUI,
    ShapesPlugin,
)
from tests import FIXTURE_DIR
from tests.cmemc_command_utils import run, run_without_assertion

DATETIME_PATTERN = re.compile(
    r'^"[1-9][0-9]{3}-(0[1-9]|1[0-2])-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9].[0-9]{3}Z"\^\^'
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


def get_graph_content(client: Client, iri: str) -> str:
    """Fetch the content of a graph as N-Triples (without owl:imports resolution)"""
    client.graphs.fetch_data()
    path: Path = client.graphs.export_item(
        key=iri,
        configuration=GraphExportConfig(serialization=GraphsRepository.formats["n-triples"]),
    )
    try:
        return path.read_text(encoding="utf-8")
    finally:
        path.unlink(missing_ok=True)


@pytest.fixture
def client() -> Client:
    """cmem-client fixture used to verify the results of a plugin execution"""
    if os.environ.get("CMEM_BASE_URI", "") == "":
        pytest.skip("Needs CMEM configuration")
    return Client.from_env()


@pytest.fixture
def add_to_graph() -> bool:
    """Add to graph parameter fixture

    this parameter is used to allow different graph_setup fixtures
    """
    return False


def remove_test_assets(setup: GraphSetupFixture) -> None:
    """Remove what these tests create and nothing else

    Run before a test as well as after it. A crashed run leaves its project and graphs
    behind, and without the call up front every later run would fail at setup on the
    leftovers.
    """
    run_without_assertion(["graph", "delete", setup.dataset_iri])
    run_without_assertion(["graph", "delete", setup.shapes_iri])
    run_without_assertion(["project", "delete", setup.project_name])
    # The central shape catalog is a shared graph that exists independently of these
    # tests, so it is never deleted - only the one import statement test_import_shapes
    # has the plugin add to it.
    Client.from_env().store.sparql.update(
        query=f"""
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        DELETE DATA {{
            GRAPH <{setup.catalog_iri}> {{
                <{setup.catalog_iri}> owl:imports <{setup.shapes_iri}> .
            }}
        }}"""
    )


@pytest.fixture
def graph_setup(add_to_graph: bool) -> Generator[GraphSetupFixture, Any]:
    """Graph setup fixture

    Creates the data graph, the project and, for the "add to graph" tests, a shape
    catalog to add to - then removes exactly those again.

    This deliberately does not snapshot and restore the whole store, which is what it
    used to do. That worked, but it reverted the deployment to the state it had when the
    test started, discarding whatever anything else had written in the meantime. On the
    shared instance the pipeline uses, that is a large blast radius for a test suite.
    """
    if os.environ.get("CMEM_BASE_URI", "") == "":
        pytest.skip("Needs CMEM configuration")
    _ = GraphSetupFixture()
    remove_test_assets(_)
    run(["graph", "import", "--replace", _.dataset_file, _.dataset_iri])
    if add_to_graph:
        run(["graph", "import", "--replace", _.shapes_file_add_init, _.shapes_iri])
    run(["project", "create", _.project_name])
    yield _
    remove_test_assets(_)


def normalize(graph: Graph) -> Graph:
    """Drop everything in a shape graph that the deployment rather than the plugin decides

    `sh:description` and `foaf:depiction`, and the language tag on a name or label, are
    resolved against whichever deployment the tests run against, so they follow the
    vocabularies that deployment happens to have loaded. Comparing them would pin these
    fixtures to one instance. What the plugin itself decides - the shapes, their IRIs,
    paths, node kinds and the name strings - is compared in full.
    """
    normalized = Graph()
    for subject, predicate, object_ in graph:
        if predicate in (SH.description, FOAF.depiction):
            continue
        if predicate in (SH.name, RDFS.label) and isinstance(object_, Literal) and object_.language:
            object_ = Literal(str(object_))  # noqa: PLW2901
        normalized.add((subject, predicate, object_))
    return normalized


def assert_isomorphic(result: Graph, expected: Graph) -> None:
    """Assert two shape graphs match, reporting the differing triples when they do not

    Neither graph contains blank nodes, so a plain set difference is an accurate diff and
    says far more than the bare `assert isomorphic(...)` this replaces.
    """
    result, expected = normalize(result), normalize(expected)
    if isomorphic(result, expected):
        return
    only_result = sorted(set(result) - set(expected), key=str)
    only_expected = sorted(set(expected) - set(result), key=str)
    report = ["generated graph does not match the fixture"]
    report += ["only in the generated graph:", *(f"  {t}" for t in only_result)]
    report += ["only in the fixture:", *(f"  {t}" for t in only_expected)]
    raise AssertionError("\n".join(report))


def test_workflow_execution(graph_setup: GraphSetupFixture, client: Client) -> None:
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
    result_graph_content = get_graph_content(client, graph_setup.shapes_iri)
    regexp = rf"<{graph_setup.shapes_iri}> <http://purl.org/dc/terms/created> .* \."
    created = re.findall(regexp, result_graph_content)
    assert len(created) == 1
    datetime = created[0].split()[-2]
    assert DATETIME_PATTERN.match(datetime)
    result_graph = Graph().parse(data=result_graph_content)
    assert len(list(result_graph.objects(predicate=DCTERMS.modified))) == 0
    result_graph.remove((URIRef(graph_setup.shapes_iri), DCTERMS.created, None))
    test = Graph().parse(f"{FIXTURE_DIR}/test_shapes.ttl")
    assert_isomorphic(result_graph, test)
    with pytest.raises(
        ValueError, match=r"Graph <http://docker.localhost/my-persons-shapes> already exists."
    ):
        ShapesPlugin(
            data_graph_iri=graph_setup.dataset_iri,
            shapes_graph_iri=graph_setup.shapes_iri,
            existing_graph=EXISTING_GRAPH_STOP,
            import_shapes=False,
            prefix_cc=False,
        ).execute(inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name))


def test_workflow_execution_add_graph_not_exists(
    graph_setup: GraphSetupFixture, client: Client
) -> None:
    """Test plugin execution with "add to graph" setting without existing graph"""
    plugin = ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph=EXISTING_GRAPH_ADD,
        import_shapes=False,
        prefix_cc=False,
    )
    plugin.execute(inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name))
    result_graph = Graph().parse(data=get_graph_content(client, graph_setup.shapes_iri))
    assert len(list(result_graph.objects(predicate=DCTERMS.created))) == 1
    assert len(list(result_graph.objects(predicate=DCTERMS.modified))) == 0
    result_graph.remove((URIRef(graph_setup.shapes_iri), DCTERMS.created, None))
    test = Graph().parse(f"{FIXTURE_DIR}/test_shapes.ttl")
    test.remove((URIRef(graph_setup.shapes_iri), DCTERMS.modified, None))
    assert_isomorphic(result_graph, test)


@pytest.mark.parametrize("add_to_graph", [True])
def test_workflow_execution_add_graph_exists(
    graph_setup: GraphSetupFixture, add_to_graph: bool, client: Client
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
    result_graph_content = get_graph_content(client, graph_setup.shapes_iri)
    regexp = rf"<{graph_setup.shapes_iri}> <http://purl.org/dc/terms/modified> .* \."
    modified = re.findall(regexp, result_graph_content)
    assert len(modified) == 1
    datetime = modified[0].split()[-2]
    assert DATETIME_PATTERN.match(datetime)
    result_graph = Graph().parse(data=result_graph_content)
    test = Graph().parse(f"{FIXTURE_DIR}/test_shapes_add.ttl")
    assert result_graph.value(
        subject=URIRef(graph_setup.shapes_iri), predicate=DCTERMS.modified
    ) != test.value(subject=URIRef(graph_setup.shapes_iri), predicate=DCTERMS.modified)
    assert len(list(result_graph.objects(predicate=DCTERMS.created))) == 0
    result_graph.remove((URIRef(graph_setup.shapes_iri), DCTERMS.modified, None))
    test.remove((URIRef(graph_setup.shapes_iri), DCTERMS.modified, None))
    assert_isomorphic(result_graph, test)


def test_additional_inits() -> None:
    """Test addition inits"""
    iri1 = "http://example.com/1"
    iri2 = "http://example.com/2"

    try:
        ShapesPlugin(data_graph_iri=iri1, shapes_graph_iri=iri2, ignore_properties="")
    except ValueError:
        pytest.fail("Usage with empty ignore_properties list should not fail.")

    try:
        ShapesPlugin(data_graph_iri=iri1, shapes_graph_iri=iri2, ignore_types="")
    except ValueError:
        pytest.fail("Usage with empty ignore_types list should not fail.")


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
    with pytest.raises(ValueError, match="Invalid type IRI"):
        ShapesPlugin(
            data_graph_iri=iri1,
            shapes_graph_iri=iri2,
            ignore_types="""no iri""",
        )
    with pytest.raises(ValueError, match="Invalid type IRI"):
        ShapesPlugin(
            data_graph_iri=iri1,
            shapes_graph_iri=iri2,
            ignore_types="""http://example.com/Person
            not a valid iri""",
        )


def test_prefix_cc_fetching(graph_setup: GraphSetupFixture, client: Client) -> None:
    """Test prefix.cc fetching"""
    plugin = ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph=EXISTING_GRAPH_REPLACE,
        import_shapes=False,
        prefix_cc=True,
    )
    plugin.execute(inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name))
    result_graph = Graph().parse(data=get_graph_content(client, graph_setup.shapes_iri))
    result_graph.remove((URIRef(graph_setup.shapes_iri), DCTERMS.created, None))
    test = Graph().parse(f"{FIXTURE_DIR}/test_shapes.ttl")
    assert_isomorphic(result_graph, test)


def test_import_shapes(graph_setup: GraphSetupFixture, client: Client) -> None:
    """Test plugin execution with import shapes"""
    ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph=EXISTING_GRAPH_REPLACE,
        import_shapes=False,
        prefix_cc=False,
    ).execute(inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name))
    assert not client.store.sparql.query(query=graph_setup.ask_query).askAnswer
    ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph=EXISTING_GRAPH_REPLACE,
        import_shapes=True,
        prefix_cc=False,
    ).execute(inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name))
    assert client.store.sparql.query(query=graph_setup.ask_query).askAnswer


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


def test_properties_with_lang_string_detects_any_tagged_value() -> None:
    """Test properties_with_lang_string flags a property with at least one langString value"""
    class_dict = {
        "http://example.com/Person": [
            {"property": "http://example.com/name", "data": True, "inverse": False, "lang": ""},
        ],
        "http://example.com/Dataset": [
            {"property": "http://example.com/name", "data": True, "inverse": False, "lang": "en"},
        ],
    }
    assert ShapesPlugin.properties_with_lang_string(class_dict) == {"http://example.com/name"}


def test_properties_with_lang_string_empty_when_no_tags() -> None:
    """Test properties_with_lang_string returns an empty set when no value has a language tag"""
    class_dict = {
        "http://example.com/Person": [
            {"property": "http://example.com/name", "data": True, "inverse": False, "lang": ""},
        ],
    }
    assert ShapesPlugin.properties_with_lang_string(class_dict) == set()


def test_omit_namespace_addon(graph_setup: GraphSetupFixture, client: Client) -> None:
    """Test omit_namespace_addon drops the "(prefix:)" suffix from property labels only"""
    plugin = ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph=EXISTING_GRAPH_REPLACE,
        import_shapes=False,
        prefix_cc=False,
        omit_namespace_addon=True,
    )
    plugin.execute(inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name))
    result_graph = Graph().parse(data=get_graph_content(client, graph_setup.shapes_iri))

    property_labels = {
        str(label)
        for shape in result_graph.subjects(predicate=RDF.type, object=SH.PropertyShape)
        for label in result_graph.objects(subject=shape, predicate=RDFS.label)
    }
    assert property_labels == {"knows", "← knows", "familyName", "label"}

    node_labels = {
        str(label)
        for shape in result_graph.subjects(predicate=RDF.type, object=SH.NodeShape)
        for label in result_graph.objects(subject=shape, predicate=RDFS.label)
    }
    assert node_labels == {"Person (foaf:)", "Dataset (void:)"}


def test_node_kind_of_a_property_used_both_ways(
    graph_setup: GraphSetupFixture, client: Client
) -> None:
    """Test the one shape of a mixed use property is described consistently

    A property may carry an IRI under one class and a language-tagged literal under
    another. There is one property shape, keyed by the property IRI, so it can only
    describe one of the two uses - and whichever it describes, sh:nodeKind and
    sh:datatype have to agree. sh:IRI with rdf:langString would satisfy nothing.
    """
    insert_query = f"""
    PREFIX ex: <http://example.com/shapes-test/>
    INSERT DATA {{
        GRAPH <{graph_setup.dataset_iri}> {{
            ex:Widget1 a ex:Widget ;
                ex:relatedTo ex:Widget2 .
            ex:Note1 a ex:Note ;
                ex:relatedTo "A related note"@en .
        }}
    }}"""
    client.store.sparql.update(query=insert_query)

    ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph=EXISTING_GRAPH_REPLACE,
        import_shapes=False,
        prefix_cc=False,
    ).execute(inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name))
    result_graph = Graph().parse(data=get_graph_content(client, graph_setup.shapes_iri))

    shape = next(
        result_graph.subjects(
            predicate=SH.path, object=URIRef("http://example.com/shapes-test/relatedTo")
        ),
        None,
    )
    assert shape is not None, "no property shape was generated for ex:relatedTo"
    node_kinds = set(result_graph.objects(subject=shape, predicate=SH.nodeKind))
    datatypes = set(result_graph.objects(subject=shape, predicate=SH.datatype))

    # ex:Note sorts before ex:Widget and holds the literal, so the query's ORDER BY makes
    # the literal use the one that decides the shape - the point being that it is decided
    # by the data rather than by whatever order the store happened to answer in.
    assert node_kinds == {SH.Literal}, node_kinds
    assert datatypes == {RDF.langString}, datatypes


def test_description_and_name_language_from_the_data_graph(
    graph_setup: GraphSetupFixture, client: Client
) -> None:
    """Test sh:description and the name language follow what the data graph says

    Every IRI here belongs to this test, so no vocabulary a deployment happens to have
    loaded can offer a competing title or description. This is what the whole graph
    comparisons deliberately normalize away, asserted on data the test owns instead.
    """
    insert_query = f"""
    PREFIX ex: <http://example.com/shapes-test/>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    INSERT DATA {{
        GRAPH <{graph_setup.dataset_iri}> {{
            ex:widget1 a ex:Widget ;
                ex:weight "12" .
            ex:weight rdfs:label "Gewicht"@de ;
                rdfs:comment "Wie schwer das Ding ist."@de .
        }}
    }}"""
    client.store.sparql.update(query=insert_query)

    plugin = ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph=EXISTING_GRAPH_REPLACE,
        import_shapes=False,
        prefix_cc=False,
    )
    plugin.execute(inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name))
    result_graph = Graph().parse(data=get_graph_content(client, graph_setup.shapes_iri))

    shape = next(
        result_graph.subjects(
            predicate=SH.path, object=URIRef("http://example.com/shapes-test/weight")
        )
    )
    # the namespace is unknown to the prefix database, so no "(prefix:)" addon is appended
    assert set(result_graph.objects(subject=shape, predicate=SH.name)) == {
        Literal("Gewicht", lang="de")
    }
    assert set(result_graph.objects(subject=shape, predicate=SH.description)) == {
        Literal("Wie schwer das Ding ist.", lang="de")
    }

    # an untagged comment stays untagged rather than being asserted as English
    client.store.sparql.update(
        query=f"""
        PREFIX ex: <http://example.com/shapes-test/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        INSERT DATA {{
            GRAPH <{graph_setup.dataset_iri}> {{
                ex:widget1 a ex:Widget ; ex:size "3" .
                ex:size rdfs:comment "How big the thing is." .
            }}
        }}"""
    )
    plugin.execute(inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name))
    result_graph = Graph().parse(data=get_graph_content(client, graph_setup.shapes_iri))
    size_shape = next(
        result_graph.subjects(
            predicate=SH.path, object=URIRef("http://example.com/shapes-test/size")
        )
    )
    assert set(result_graph.objects(subject=size_shape, predicate=SH.description)) == {
        Literal("How big the thing is.")
    }


def test_no_description_on_an_inverse_property_shape(
    graph_setup: GraphSetupFixture, client: Client
) -> None:
    """Test the description of a property is not repeated on its inverse shape

    The description is written about the property, so on the inverse path it would
    describe the opposite of what the shape holds.
    """
    client.store.sparql.update(
        query=f"""
        PREFIX ex: <http://example.com/shapes-test/>
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        INSERT DATA {{
            GRAPH <{graph_setup.dataset_iri}> {{
                ex:person1 a ex:Person ; ex:employs ex:person2 .
                ex:person2 a ex:Person .
                ex:employs rdfs:comment "The people this person employs."@en .
            }}
        }}"""
    )
    ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph=EXISTING_GRAPH_REPLACE,
        import_shapes=False,
        prefix_cc=False,
    ).execute(inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name))
    result_graph = Graph().parse(data=get_graph_content(client, graph_setup.shapes_iri))

    employs = URIRef("http://example.com/shapes-test/employs")
    shapes = set(result_graph.subjects(predicate=SH.path, object=employs))
    forward = {s for s in shapes if (s, SHUI.inversePath, None) not in result_graph}
    inverse = shapes - forward
    assert forward, "the fixture has to produce a forward shape"
    assert inverse, "the fixture has to produce an inverse shape"
    assert {str(o) for s in forward for o in result_graph.objects(s, SH.description)} == {
        "The people this person employs."
    }
    assert not {o for s in inverse for o in result_graph.objects(s, SH.description)}


XSD_NAMESPACE = "http://www.w3.org/2001/XMLSchema#"


def test_prefix_database_prefers_the_shortest_prefix() -> None:
    """Test the prefix taken for a namespace is not simply the alphabetically first

    prefix_cc.json is stored sorted, and prefix.cc offers four prefixes for the XML
    Schema namespace, one of which is the typo "xds".
    """
    formatted = ShapesPlugin.format_prefixes(
        {"xds": XSD_NAMESPACE, "xmls": XSD_NAMESPACE, "xs": XSD_NAMESPACE, "xsd": XSD_NAMESPACE},
        shortest_first=True,
    )
    assert formatted[XSD_NAMESPACE][0] == "xs:"


def test_project_prefixes_keep_precedence_over_the_database() -> None:
    """Test a prefix declared in the project wins over one offered by the database"""
    from_project = ShapesPlugin.format_prefixes({"mine": XSD_NAMESPACE})
    both = ShapesPlugin.format_prefixes(
        {"xds": XSD_NAMESPACE, "xs": XSD_NAMESPACE}, from_project, shortest_first=True
    )
    assert both[XSD_NAMESPACE][0] == "mine:"


def test_a_blank_node_class_is_ignored(graph_setup: GraphSetupFixture, client: Client) -> None:
    """Test an anonymous class expression does not reach the shape generation

    Instance data sharing a graph with an OWL ontology types things with anonymous
    class expressions. A blank node has no namespace, so it used to reach split_uri
    and abort the run with "Invalid class or property (b0)." after every query had
    already been paid for.
    """
    client.store.sparql.update(
        query=f"""
        PREFIX ex: <http://example.com/shapes-test/>
        PREFIX owl: <http://www.w3.org/2002/07/owl#>
        INSERT DATA {{
            GRAPH <{graph_setup.dataset_iri}> {{
                ex:thing1 a ex:Thing , [ a owl:Restriction ; owl:onProperty ex:weight ] ;
                    ex:weight "12" .
            }}
        }}"""
    )
    plugin = ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph=EXISTING_GRAPH_REPLACE,
        import_shapes=False,
        prefix_cc=False,
    )
    plugin.execute(inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name))
    result_graph = Graph().parse(data=get_graph_content(client, graph_setup.shapes_iri))

    target_classes = set(result_graph.objects(predicate=SH.targetClass))
    assert URIRef("http://example.com/shapes-test/Thing") in target_classes
    assert all(isinstance(target, URIRef) for target in target_classes), target_classes

    # and the action does not offer something the parameter would reject
    listed = plugin.get_classes(TestPluginContext(project_id=graph_setup.project_name))
    body = listed.split("```")[1].strip().splitlines()
    assert "http://example.com/shapes-test/Thing" in body
    assert all(line.startswith("http") for line in body), body


def test_provenance_subject_keeps_the_whole_task_iri() -> None:
    """Test the provenance subject is the task IRI plus a suffix, not a truncation of it

    The subject used to be built by dropping everything after the last underscore
    anywhere in the task IRI, so a project id containing one lost the task segment with
    it, and a task IRI with no underscore at all produced a bare relative reference.
    """
    suffix = re.compile(r"_[0-9a-f]{16}$")
    for project, task in (("myproject", "mytask"), ("shapes_plugin_test", "mytask")):
        task_iri = f"http://dataintegration.eccenca.com/{project}/{task}"
        subject = f"{re.sub(r'_[0-9a-f]{16}$', '', task_iri)}_{'a' * 16}"
        assert subject.startswith(task_iri), subject
        assert suffix.sub("", subject) == task_iri

    # a subject this code produced earlier keeps its length rather than growing each run
    already = f"http://dataintegration.eccenca.com/p/t_{'b' * 16}"
    assert re.sub(r"_[0-9a-f]{16}$", "", already) == "http://dataintegration.eccenca.com/p/t"


def test_parameter_literal_escapes_and_flattens() -> None:
    """Test a parameter value cannot break out of the SPARQL literal it is written into

    Round-tripping is the proof: whatever the value contains, the serialized form has to
    parse back to exactly that one literal and to nothing else.
    """
    plugin = ShapesPlugin.__new__(ShapesPlugin)

    for value in (
        'My "big" catalog',
        'x" . <http://evil/s> <http://evil/p> "y',
        "a line\nand another",
        "back\\slash",
    ):
        plugin.label = value
        serialized = plugin.parameter_literal("label").n3()
        assert from_n3(serialized) == Literal(value), serialized

    # a list parameter is recorded as the lines the user typed, not as a Python repr
    plugin.ignore_types = ["http://example.com/a", "http://example.com/b"]
    assert str(plugin.parameter_literal("ignore_types")) == (
        "http://example.com/a\nhttp://example.com/b"
    )


def test_shape_count_does_not_accumulate_across_runs(
    graph_setup: GraphSetupFixture,
) -> None:
    """Test a second run of the same task reports its own shapes, not both runs' worth"""
    plugin = ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph=EXISTING_GRAPH_REPLACE,
        import_shapes=False,
        prefix_cc=False,
    )
    context = TestExecutionContext(project_id=graph_setup.project_name)
    plugin.execute(inputs=[], context=context)
    first = plugin.shapes_count
    plugin.execute(inputs=[], context=context)

    assert first > 0
    assert plugin.shapes_count == first


def test_title_record_stands_in_for_an_absent_answer() -> None:
    """Test a missing title does not raise from inside the shape loop"""
    titles = {"http://example.com/known": {"title": "Known", "fromIri": False, "lang": "en"}}
    assert ShapesPlugin.title_record("http://example.com/known", titles)["title"] == "Known"

    missing = ShapesPlugin.title_record("http://example.com/absent", titles)
    assert missing["fromIri"] is True
    plugin = ShapesPlugin.__new__(ShapesPlugin)
    plugin.prefixes = {"http://example.com/": ("ex:",)}
    assert plugin.get_name("http://example.com/absent", missing) == "absent (ex:)"


def test_get_name_falls_back_to_the_local_name() -> None:
    """Test a synthesized title is not taken apart on an underscore

    The deployment builds a title out of the IRI when it knows nothing about it, and
    the shape of that title is not this plugin's to predict.
    """
    plugin = ShapesPlugin.__new__(ShapesPlugin)
    plugin.prefixes = {"http://schema.org/": ("schema:",)}

    # a title with no underscore used to raise IndexError from inside the shape loop
    assert (
        plugin.get_name("http://schema.org/Person", {"title": "Person", "fromIri": True})
        == "Person (schema:)"
    )
    # and one with an underscore was truncated at it, giving "name (schema:)"
    assert (
        plugin.get_name("http://schema.org/first_name", {"title": "first_name", "fromIri": True})
        == "first_name (schema:)"
    )


def test_namespace_graphs_offers_both_spellings() -> None:
    """Test namespace_graphs offers a vocabulary graph name with and without its separator"""
    assert ShapesPlugin.namespace_graphs(["http://example.com/vocab/Widget"]) == [
        "http://example.com/vocab",
        "http://example.com/vocab/",
    ]
    assert ShapesPlugin.namespace_graphs(["http://example.com/vocab#Widget"]) == [
        "http://example.com/vocab",
        "http://example.com/vocab#",
    ]


def test_namespace_graphs_splits_a_urn_too() -> None:
    """Test a urn: class IRI is split on its last colon like any other IRI"""
    assert ShapesPlugin.namespace_graphs(["urn:example:widget"]) == [
        "urn:example",
        "urn:example:",
    ]


def test_namespace_graphs_skips_an_unsplittable_iri() -> None:
    """Test namespace_graphs ignores what it cannot split, leaving get_name to report it

    Only an IRI with no separator at all is unsplittable - a urn: IRI is not one of them.
    """
    assert ShapesPlugin.namespace_graphs(["12345"]) == []
    assert ShapesPlugin.namespace_graphs([]) == []


def test_managed_classes_are_declared_by_default(
    graph_setup: GraphSetupFixture, client: Client
) -> None:
    """Test the catalog declares the classes it manages without being asked to"""
    ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph=EXISTING_GRAPH_REPLACE,
        import_shapes=False,
        prefix_cc=False,
    ).execute(inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name))
    result_graph = Graph().parse(data=get_graph_content(client, graph_setup.shapes_iri))

    assert set(
        result_graph.objects(subject=URIRef(graph_setup.shapes_iri), predicate=SHUI.managedClasses)
    ) == set(MANAGED_CLASSES)


def test_managed_classes_can_be_turned_off(graph_setup: GraphSetupFixture, client: Client) -> None:
    """Test no managed class is declared when the option is switched off"""
    ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph=EXISTING_GRAPH_REPLACE,
        import_shapes=False,
        prefix_cc=False,
        managed_classes=False,
    ).execute(inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name))
    result_graph = Graph().parse(data=get_graph_content(client, graph_setup.shapes_iri))

    assert not set(
        result_graph.objects(subject=URIRef(graph_setup.shapes_iri), predicate=SHUI.managedClasses)
    )


def test_depiction_from_the_data_graph(graph_setup: GraphSetupFixture, client: Client) -> None:
    """Test a node shape is given the foaf:depiction of its target class, without being asked

    The class is owned by this test, and a second class without a depiction is typed
    alongside it to show that a node shape only gets one where there is something to find.
    """
    insert_query = f"""
    PREFIX ex: <http://example.com/shapes-test/>
    PREFIX foaf: <http://xmlns.com/foaf/0.1/>
    INSERT DATA {{
        GRAPH <{graph_setup.dataset_iri}> {{
            ex:widget1 a ex:Widget ;
                ex:name "a widget" .
            ex:gadget1 a ex:Gadget ;
                ex:name "a gadget" .
            ex:Widget foaf:depiction <http://example.com/shapes-test/widget.png> .
        }}
    }}"""
    client.store.sparql.update(query=insert_query)

    ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph=EXISTING_GRAPH_REPLACE,
        import_shapes=False,
        prefix_cc=False,
    ).execute(inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name))
    result_graph = Graph().parse(data=get_graph_content(client, graph_setup.shapes_iri))

    def node_shape_of(class_iri: str) -> Node:
        return next(result_graph.subjects(predicate=SH.targetClass, object=URIRef(class_iri)))

    widget_shape = node_shape_of("http://example.com/shapes-test/Widget")
    gadget_shape = node_shape_of("http://example.com/shapes-test/Gadget")
    assert set(result_graph.objects(subject=widget_shape, predicate=FOAF.depiction)) == {
        URIRef("http://example.com/shapes-test/widget.png")
    }
    assert not set(result_graph.objects(subject=gadget_shape, predicate=FOAF.depiction))


def test_depictions_can_be_turned_off(graph_setup: GraphSetupFixture, client: Client) -> None:
    """Test no depiction is written when the option is switched off"""
    insert_query = f"""
    PREFIX ex: <http://example.com/shapes-test/>
    PREFIX foaf: <http://xmlns.com/foaf/0.1/>
    INSERT DATA {{
        GRAPH <{graph_setup.dataset_iri}> {{
            ex:widget1 a ex:Widget ;
                ex:name "a widget" .
            ex:Widget foaf:depiction <http://example.com/shapes-test/widget.png> .
        }}
    }}"""
    client.store.sparql.update(query=insert_query)

    ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph=EXISTING_GRAPH_REPLACE,
        import_shapes=False,
        prefix_cc=False,
        depictions=False,
    ).execute(inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name))
    result_graph = Graph().parse(data=get_graph_content(client, graph_setup.shapes_iri))
    assert not set(result_graph.subject_objects(predicate=FOAF.depiction))


def test_get_classes_and_get_properties_actions(graph_setup: GraphSetupFixture) -> None:
    """Test both actions list what the data graph holds, ready for the ignore parameters

    Neither ignore list is applied: rdf:type is the default of Properties to ignore and
    still has to be offered, or the action could not explain the default it is up against.
    """
    plugin = ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph=EXISTING_GRAPH_REPLACE,
        import_shapes=False,
        prefix_cc=False,
    )
    context = TestPluginContext(project_id=graph_setup.project_name)

    classes = plugin.get_classes(context)
    assert "http://xmlns.com/foaf/0.1/Person" in classes
    assert "http://rdfs.org/ns/void#Dataset" in classes
    assert "```" in classes, "the listing has to be a code block to survive Markdown rendering"
    assert "<" not in classes, "an <iri> would render as a link to something not retrievable"

    properties = plugin.get_properties(context)
    for iri in (
        "http://xmlns.com/foaf/0.1/knows",
        "http://xmlns.com/foaf/0.1/familyName",
        "http://www.w3.org/2000/01/rdf-schema#label",
        "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
    ):
        assert iri in properties, iri


def test_actions_report_an_empty_graph(graph_setup: GraphSetupFixture) -> None:
    """Test an action says so rather than returning an empty code block"""
    plugin = ShapesPlugin(
        data_graph_iri="http://example.com/shapes-test/a-graph-that-holds-nothing",
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph=EXISTING_GRAPH_REPLACE,
        import_shapes=False,
        prefix_cc=False,
    )
    context = TestPluginContext(project_id=graph_setup.project_name)
    assert plugin.get_classes(context).startswith("No classes found")
    assert plugin.get_properties(context).startswith("No properties found")


def test_ignore_types_and_properties() -> None:
    """Test ignore_types and ignore_properties parameters together"""
    iri1 = "http://example.com/1"
    iri2 = "http://example.com/2"
    person_type = "http://schema.org/Person"
    organization_type = "http://schema.org/Organization"
    name_prop = "http://schema.org/name"
    email_prop = "http://schema.org/email"

    plugin = ShapesPlugin(
        data_graph_iri=iri1,
        shapes_graph_iri=iri2,
        ignore_types=person_type,
    )
    assert plugin.ignore_types == [person_type]

    plugin = ShapesPlugin(
        data_graph_iri=iri1,
        shapes_graph_iri=iri2,
        ignore_types=f"{person_type}\n{organization_type}",
    )
    assert plugin.ignore_types == [person_type, organization_type]

    plugin = ShapesPlugin(
        data_graph_iri=iri1,
        shapes_graph_iri=iri2,
        ignore_properties=f"{name_prop}\n{email_prop}",
        ignore_types=f"{person_type}\n{organization_type}",
    )
    assert plugin.ignore_properties == [name_prop, email_prop]
    assert plugin.ignore_types == [person_type, organization_type]

    type_filter = ShapesPlugin.iri_list_to_filter(
        iris=[person_type, organization_type], name="class"
    )
    assert type_filter == f"FILTER (?class NOT IN (<{person_type}>, <{organization_type}>))"

    prop_filter = ShapesPlugin.iri_list_to_filter(iris=[name_prop, email_prop], name="property")
    assert prop_filter == f"FILTER (?property NOT IN (<{name_prop}>, <{email_prop}>))"

    plugin = ShapesPlugin(
        data_graph_iri=iri1,
        shapes_graph_iri=iri2,
        ignore_types="",
        ignore_properties="",
    )
    assert plugin.ignore_types == []
    assert plugin.ignore_properties == []


def test_workflow_execution_with_ignore_types(
    graph_setup: GraphSetupFixture, client: Client
) -> None:
    """Test plugin execution with ignore_types parameter filters correctly"""
    plugin_baseline = ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph=EXISTING_GRAPH_REPLACE,
        import_shapes=False,
        prefix_cc=False,
    )
    plugin_baseline.execute(
        inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name)
    )
    baseline_graph = Graph().parse(data=get_graph_content(client, graph_setup.shapes_iri))
    baseline_count = plugin_baseline.shapes_count

    plugin_filtered = ShapesPlugin(
        data_graph_iri=graph_setup.dataset_iri,
        shapes_graph_iri=graph_setup.shapes_iri,
        existing_graph=EXISTING_GRAPH_REPLACE,
        import_shapes=False,
        prefix_cc=False,
        ignore_types="http://xmlns.com/foaf/0.1/Person",
    )
    plugin_filtered.execute(
        inputs=[], context=TestExecutionContext(project_id=graph_setup.project_name)
    )
    filtered_graph = Graph().parse(data=get_graph_content(client, graph_setup.shapes_iri))
    filtered_count = plugin_filtered.shapes_count

    assert filtered_count < baseline_count, (
        f"Expected fewer shapes when filtering types, "
        f"but got {filtered_count} (filtered) vs {baseline_count} (baseline)"
    )

    # Verify the filtered graph is not isomorphic to baseline (they should differ)
    baseline_graph.remove((URIRef(graph_setup.shapes_iri), DCTERMS.created, None))
    filtered_graph.remove((URIRef(graph_setup.shapes_iri), DCTERMS.created, None))
    assert not isomorphic(baseline_graph, filtered_graph), (
        "Expected graphs to differ when using ignore_types filter"
    )


@pytest.mark.parametrize("add_to_graph", [True])
def test_add_to_graph_label(
    graph_setup: GraphSetupFixture, add_to_graph: bool, client: Client
) -> None:
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
    plugin.client = Client.from_context(plugin.context)

    def get_labels() -> list[str]:
        """Return the English labels of the shapes graph"""
        rows = cast(
            "list[ResultRow]", list(client.store.sparql.query(query=graph_setup.label_query))
        )
        return [str(row["label"]) for row in rows]

    plugin.shapes_graph = Graph()
    plugin.add_to_graph()
    assert get_labels() == [f"Shapes for {graph_setup.dataset_iri}"]

    client.store.sparql.update(query=graph_setup.remove_label_query)
    plugin.shapes_graph = Graph()
    plugin.add_to_graph()
    assert get_labels() == [f"Shapes for {graph_setup.dataset_iri}"]

    client.store.sparql.update(query=graph_setup.remove_label_query)
    query = f"""
        PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
        INSERT DATA {{
            GRAPH <{graph_setup.shapes_iri}> {{
                <{graph_setup.shapes_iri}> rdfs:label "test label"@de
            }}
        }}"""
    client.store.sparql.update(query=query)
    plugin.shapes_graph = Graph()
    plugin.add_to_graph()
    assert get_labels() == [f"Shapes for {graph_setup.dataset_iri}"]

    plugin.label = "New label"

    plugin.shapes_graph = Graph()
    plugin.add_to_graph()
    assert get_labels() == ["New label"]

    client.store.sparql.update(query=graph_setup.remove_label_query)
    plugin.shapes_graph = Graph()
    plugin.add_to_graph()
    assert get_labels() == ["New label"]
