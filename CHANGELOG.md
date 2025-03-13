# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/) and this project adheres to [Semantic Versioning](https://semver.org/)

## [3.0.1] 2025-03-13

### Fixed

- Fixed error when "Properties to ignore" field is empty, or contains empty lines.

### Changed

- Removed warning regarding "Fetch namespace prefixes from prefix.cc" parameter in documentation,
since no information about the used namespaces is revealed when downloading the namespace list.

## [3.0.0] 2025-03-05

### Added

- Parameter to specify the label of the shapes graph. If no label is given for a new graph, a label is generated.
If the shapes graph exists, its label can be overwritten or kept.
- Add `dcterms:source [data graph IRI]` to the shapes graph
- Option to add plugin provenance to the shapes graph

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

