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
  fixtures/                   # TTL test data (test_shapes.ttl, etc.)
pyproject.toml                # Poetry config: rdflib, cmem-cmempy, cmem-plugin-base deps
Taskfile.yaml                 # task (taskfile.dev) targets for check/build/format
.pre-commit-config.yaml       # local hooks: ruff, poetry-check, trivy
```

The entire plugin is a single class `ShapesPlugin(WorkflowPlugin)` in `plugin_shapes.py` (~700 lines). It uses the `@Plugin(...)` decorator to declare parameters (graph inputs, boolean flags for prefix.cc fetching, provenance, shape import, etc.) and implements `execute()` as the entry point.

Key responsibilities in `ShapesPlugin`:
- `get_prefixes()` — fetch namespace prefixes (from CMEM project DB or prefix.cc, fallback to bundled `prefix_cc.json`)
- `get_class_dict()` — SPARQL query that retrieves distinct `(class, property, data?, inverse?)` tuples from the data graph
- `create_shapes()` — walks the class dict and adds SHACL triples to an in-memory rdflib Graph
- `create_graph()` / `add_to_graph()` — persist via CMEM's DP API (streamed insert / SPARQL UPDATE)
- `import_shapes_graph()` — add `owl:imports` to the central CMEM shapes catalog

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

- **CMEM integration**: The plugin communicates with CMEM via `cmem.cmempy` (DP API for graph read/write, SPARQL endpoint for queries). User auth is set up via `setup_cmempy_user_access(context.user)`.
- **Shape generation**: Uses rdflib Graph as the working shapes container; serialized to N-Triples before streaming into CMEM.
- **Naming**: Class and property names are derived from their IRIs — prefix is resolved from namespace, title fetched via CMEM explore API (`/api/explore/title`).
- **Inverses**: Object properties used in reverse direction (object → subject) are detected separately in SPARQL and marked with `shui:inversePath` + a `← ` prefix in labels.
- **Graph handling modes** (`existing_graph` parameter): `stop` (default, abort if target exists), `replace`, or `add`.
- **Provenance**: Optional — posts plugin metadata as RDF triples into the shapes graph via SPARQL UPDATE.

## Testing Notes

- Tests marked with `graph_setup` fixture require a running CMEM instance (`CMEM_BASE_URI` env var). They import/export the entire DB store via `cmemc` CLI around test execution.
- Pure unit tests (no fixture) validate IRI parsing, FILTER generation, and parameter validation — these run without CMEM.
- Fixtures live in `tests/fixtures/` as TTL files for isomorphism checks.

## Code Style & Linting

- **Ruff**: line-length 100, target py313. Many rule groups ignored (ANN204, COM812, D1xx, FBTS, etc.). See `pyproject.toml` `[tool.ruff.lint]`.
- **mypy**: `warn_return_any = true`, `ignore_missing_imports = true`.
- All code uses `from __future__ import annotations` style (no imports needed — py313 feature). Docstrings required on modules.