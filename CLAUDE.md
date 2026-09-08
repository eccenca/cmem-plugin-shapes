# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`cmem-plugin-shapes` is a Python plugin for [eccenca Corporate Memory](https://documentation.eccenca.com) that generates SHACL (Shapes Constraint Language) node and property shapes from instance data in a knowledge graph. It analyzes an input RDF graph and produces `sh:NodeShape` and `sh:PropertyShape` graphs with UUID5-derived URIs, human-readable labels using namespace prefixes, and optional provenance metadata.

## Codebase Structure

```
cmem_plugin_shapes/
  __init__.py                 # Package marker
  plugin_shapes.py            # Single module: ShapesPlugin class + helpers
tests/
  test_shapes.py              # Plugin unit + integration tests
  cmemc_command_utils.py      # Helpers for running cmemc CLI in tests
  fixture_dir/                # TTL test data (test_shapes.ttl, etc.)
pyproject.toml                # Poetry config: rdflib, cmem-client, cmem-plugin-base deps
Taskfile.yaml                 # task (taskfile.dev) targets for check/build/format
.pre-commit-config.yaml       # local hooks: ruff, poetry-check, trivy
```

The entire plugin is a single class `ShapesPlugin(WorkflowPlugin)` in `plugin_shapes.py` (~1150 lines). It uses the `@Plugin(...)` decorator to declare parameters (graph inputs, boolean flags for prefix.cc fetching, provenance, shape import, etc.) and implements `execute()` as the entry point.

Key responsibilities in `ShapesPlugin`:
- `get_prefixes()` — fetch namespace prefixes (from the project, or prefix.cc, falling back to the bundled `prefix_cc.json`)
- `get_class_dict()` — ordered SPARQL query returning `(class, property, data?, inverse?, lang)` rows from the data graph
- `resolve()` / `get_descriptions()` / `get_depictions()` — batched lookups of names, descriptions and depictions
- `create_shapes()` / `add_property_shape()` — walk the class dict and add SHACL triples to an in-memory rdflib Graph
- `create_graph()` / `add_to_graph()` — decide the bookkeeping, then both stream through `write_shapes()`
- `import_shapes_graph()` — add `owl:imports` to the central shape catalog
- `get_classes()` / `get_properties()` — the two `PluginAction`s, listing what the data graph holds

## Development Commands

All commands use `task` (Taskfile.yaml). Ensure Poetry is installed and a `.venv` exists.

| Command | Description |
|---------|-------------|
| `task check` | Full suite: linters + pytest |
| `task check:linters` | ruff + mypy + deptry + trivy |
| `task check:ruff` | Lint + format check |
| `task check:mypy` | Type checking |
| `task check:deptry` | Unused/missing dependency check |
| `task check:trivy` | Vulnerability scan |
| `task check:pytest` | Run tests (with coverage, HTML report) |
| `task format:fix` | ruff format + safe auto-fixes |
| `task format:fix-unsafe` | ruff format + all auto-fixes |
| `task build` | `poetry build` + export requirements.txt |
| `task clean` | Remove dist, caches, pyc files |
| `task update_prefixes` | Refresh prefix.cc data (dev helper) |

To run a single test:
```bash
poetry run pytest tests/test_shapes.py::test_filter_creation -v
```

## Architecture Notes

- **Corporate Memory integration**: The plugin reaches the deployment through [`cmem-client`](https://pypi.org/project/cmem-client/), built from the context it was handed — `Client.from_context(context)` in `execute()`, `get_client(context)` in the two actions. `cmem.cmempy` is deprecated and this plugin no longer uses it.
- **Shape generation**: Uses rdflib Graph as the working shapes container; serialized to N-Triples before streaming into CMEM.
- **Naming**: Names come from the explore API title helper, batched through `POST /api/explore/titles`, with the namespace prefix appended. Where a namespace offers several prefixes the shortest is taken, since the database is stored alphabetically and its first entry is sometimes a typo.
- **Inverses**: Object properties used in reverse direction (object → subject) are detected separately in SPARQL and marked with `shui:inversePath` + a `← ` prefix in labels.
- **Graph handling modes** (`existing_graph` parameter): `stop` (default, abort if target exists), `replace`, or `add`.
- **Provenance**: Optional — posts task metadata as RDF triples into the shape catalog via SPARQL UPDATE. Values go through `Literal.n3()`, never string interpolation.

## Testing Notes

- Tests using the `graph_setup` fixture require a running Corporate Memory deployment (`CMEM_BASE_URI`). The fixture creates the data graph, the catalog and the project, and removes exactly those again — before the test as well as after it, so a crashed run does not block the next one. It does **not** snapshot the store.
- Pure unit tests (no fixture) validate IRI parsing, FILTER generation, prefix selection and parameter validation — these run without a deployment.
- Fixtures live in `tests/fixture_dir/` as TTL files for isomorphism checks. `assert_isomorphic()` normalizes away what the deployment rather than the plugin decides — `sh:description`, `foaf:depiction` and the language tag on a name — so the comparisons do not depend on which vocabularies an instance has loaded.

## Code Style & Linting

- **Ruff**: line-length 100, target py313. Many rule groups ignored (ANN204, COM812, D1xx, FBTS, etc.). See `pyproject.toml` `[tool.ruff.lint]`.
- **mypy**: `warn_return_any = true`, `ignore_missing_imports = true`.
- All code uses `from __future__ import annotations` style (no imports needed — py313 feature). Docstrings required on modules.