# cmem-plugin-shapes

Generate SHACL node and property shapes from a data graph.

[![eccenca Corporate Memory](https://img.shields.io/badge/eccenca-Corporate%20Memory-orange)](https://documentation.eccenca.com) [![workflow](https://github.com/eccenca/cmem-plugin-shapes/actions/workflows/check.yml/badge.svg)](https://github.com/eccenca/cmem-plugin-pyshacl/actions) [![pypi version](https://img.shields.io/pypi/v/cmem-plugin-shapes)](https://pypi.org/project/cmem-plugin-shapes/) [![license](https://img.shields.io/pypi/l/cmem-plugin-shapes)](https://pypi.org/project/cmem-plugin-shapes)


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

Attempt to fetch namespace prefixes from [http://prefix.cc](http://prefix.cc) instead of from the local database.
If this fails, fall back on local database.


[![eccenca Corporate Memory](https://img.shields.io/badge/eccenca-Corporate%20Memory-orange)](https://documentation.eccenca.com)   

## Development

- Run [task](https://taskfile.dev/) to see all major development tasks.
- Use [pre-commit](https://pre-commit.com/) to avoid errors before commit.
- This repository was created with [this copier template](https://github.com/eccenca/cmem-plugin-template).

