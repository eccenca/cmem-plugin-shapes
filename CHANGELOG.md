# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/) and this project adheres to [Semantic Versioning](https://semver.org/)


## [Unreleased] 

### Added

- Add `dcterms:source [data graph IRI]` to the shapes graph
- Option to add plugin provenance to the shapes graph

### Changed

- When adding to existing graph the source graph IRI is appended to the label. If the existing label does not conform
to the format `"Shapes for: [IRI], [IRI2], ..."` it is stored as `rdfs:comment "Previous label: [previous label]"` and a label with the
new data graph IRI is added.

## [2.0.1] 2025-02-19

### Changed

- Also count node shapes for the execution report
- New icon

## [2.0.0] 2025-02-10

### Changed

- Replaced the bool parameter "Overwrite Shape Catalog" with the parameter "Handle existing output graph" with the options:
  - replace the graph
  - add the result shapes to the graph
  - stop the workflow if the specified output graph already exists
- Allow custom entries for Input data graph parameter
- Recheck if graph exists before importing created shapes graph

### Added

- Add dcterms:created datetime for new/replaced output graphs or dcterms:modified datetime for updated output graphs

### Fixed

- Fixed issue with prefixes from prefix.cc not used correctly


## [1.0.0] 2025-02-03

- initial version

