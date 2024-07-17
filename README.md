# cmem-plugin-shapes

Generate SHACL node and property shapes from a data graph
<<<<<<< before updating

## Parameters

### Data graph

The IRI of the data graph to be analyzed.

### SHACL shapes graph

The IRI of the SHACL graph to be produced.

### Overwrite shapes graph if it exists

If enabled and a graph with the specified SHACL shapes graph IRI exists, the graph will be
overwritten with the result. If disabled and such a graph exists, the plugin execution fails.

### Import shapes graph in CMEM Shapes Catalog

If enabled, the resulting SHACL shapes graph is imported with `owl:imports` in the CMEM Shapes Catalog.

### Fetch namespace prefixes from prefix.cc

If enabled, attempt to fetch namespace prefixes from [http://prefix.cc](http://prefix.cc) instead of from the local database.
If this fails, fall back on local database.
=======
>>>>>>> after updating

[![eccenca Corporate Memory](https://img.shields.io/badge/eccenca-Corporate%20Memory-orange)](https://documentation.eccenca.com)   

## Development

- Run [task](https://taskfile.dev/) to see all major development tasks.
- Use [pre-commit](https://pre-commit.com/) to avoid errors before commit.
- This repository was created with [this copier template](https://github.com/eccenca/cmem-plugin-template).

