# cmem-plugin-shapes

An [eccenca](https://eccenca.com) [Corporate Memory](https://documentation.eccenca.com) workflow plugin generating SHACL node and property shapes from data graphs.

[![eccenca Corporate Memory](https://img.shields.io/badge/eccenca-Corporate%20Memory-orange)](https://documentation.eccenca.com) [![workflow](https://github.com/eccenca/cmem-plugin-shapes/actions/workflows/check.yml/badge.svg)](https://github.com/eccenca/cmem-plugin-pyshacl/actions) [![pypi version](https://img.shields.io/pypi/v/cmem-plugin-shapes)](https://pypi.org/project/cmem-plugin-shapes/) [![license](https://img.shields.io/pypi/l/cmem-plugin-shapes)](https://pypi.org/project/cmem-plugin-shapes)


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


[![eccenca Corporate Memory](https://img.shields.io/badge/eccenca-Corporate%20Memory-orange)](https://documentation.eccenca.com)   

## Development

- Run [task](https://taskfile.dev/) to see all major development tasks.
- Use [pre-commit](https://pre-commit.com/) to avoid errors before commit.
- This repository was created with [this copier template](https://github.com/eccenca/cmem-plugin-template).

