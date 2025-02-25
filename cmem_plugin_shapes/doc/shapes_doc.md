A task to generate SHACL node and property shapes from an instance data knowledge graph.
    
## Parameters

**<a id="parameter_doc_data_graph_iri">Input data graph</a>**

The Knowledge Graph containing the instance data to be analyzed for the SHACL shapes generation.

**<a id="parameter_doc_shapes_graph_iri">Output Shape Catalog</a>**

The Knowledge Graph, the generated shapes will be added to.

**<a id="parameter_doc_existing_graph">Handle existing output graph</a>**

Add result to the existing graph (add result to graph), overwrite the existing graph with the result (replace existing
graph with result), or stop the workflow if the output graph already exists (stop workflow if output graph exists).

**<a id="parameter_doc_import_shapes">Import the output graph into the central Shapes Catalog</a>**

Import the SHACL shapes graph in the CMEM Shapes catalog by adding an `owl:imports` statement to the central CMEM Shapes Catalog.
If not imported, the new shapes are not activated and used.

**<a id="parameter_doc_prefix_cc">Additionally fetch namespace prefixes from prefix.cc</a>**

Attempt to fetch namespace prefixes from prefix.cc instead of  from the local database.
If this fails, fall back on local database.
Prefixes defined in the Corporate Memory project will override prefixes defined in the external database.
            
WARNING: Enabling this flag reveals information to an external service.

**<a id="parameter_doc_ignore_properties">Properties to ignore</a>**

Provide the list of properties (as IRIs) for which you do not want to create property shapes.
Example:
```
http://www.w3.org/1999/02/22-rdf-syntax-ns#type
http://xmlns.com/foaf/0.1/familyName
```

**<a id="parameter_doc_plugin_provenance">Include plugin provenance</a>**

Add information about the plugin and plugin settings to the shapes graph.
