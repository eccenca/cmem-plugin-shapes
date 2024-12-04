A task generating SHACL node and property shapes from a data graph.
    
## Parameters

### Data graph

The input data graph to be analyzed for the SHACL shapes generation.

### Output SHACL shapes graph

The output SHACL shapes graph.

### Overwrite shapes graph if it exists

Overwrite the output SHACL shapes graph if it exists. If disabled and the graph exists, the plugin execution fails.

### Import shapes graph in CMEM Shapes Catalog

Import the SHACL shapes graph in the CMEM Shapes catalog by adding an `owl:imports` statement to the CMEM Shapes Catalog.

### Use prefixes

Attempt to fetch namespace prefixes from http://prefix.cc instead of from the local database. If this fails, fall back
on local database. Prefixes defined in the CMEM project override prefixes defined in the external database.
