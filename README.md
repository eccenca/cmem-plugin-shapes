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


[![eccenca Corporate Memory][cmem-shield]][cmem-link][![workflow](https://github.com/eccenca/cmem-plugin-shapes/actions/workflows/check.yml/badge.svg)](https://github.com/eccenca/cmem-plugin-shapes/actions)  
[![poetry][poetry-shield]][poetry-link] [![ruff][ruff-shield]][ruff-link] [![mypy][mypy-shield]][mypy-link] [![copier][copier-shield]][copier]

## Development

- Run [task](https://taskfile.dev/) to see all major development tasks.
- Use [pre-commit](https://pre-commit.com/) to avoid errors before commit.
- This repository was created with [this copier template](https://github.com/eccenca/cmem-plugin-template).

[cmem-link]: https://documentation.eccenca.com
[cmem-shield]: https://img.shields.io/endpoint?url=https://dev.documentation.eccenca.com/badge.json
[poetry-link]: https://python-poetry.org/
[poetry-shield]: https://img.shields.io/endpoint?url=https://python-poetry.org/badge/v0.json
[ruff-link]: https://docs.astral.sh/ruff/
[ruff-shield]: https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json&label=Code%20Style
[mypy-link]: https://mypy-lang.org/
[mypy-shield]: https://www.mypy-lang.org/static/mypy_badge.svg
[copier]: https://copier.readthedocs.io/
[copier-shield]: https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/copier-org/copier/master/img/badge/badge-grayscale-inverted-border-purple.json
