<!-- markdownlint-disable MD012 MD013 MD024 MD033 -->
# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/) and this project adheres to [Semantic Versioning](https://semver.org/)

## [Unreleased]

### Changed

- Update template to 8.2.1.
- Allow urn URIs in graph parameters.


## [4.3.0] 2025-12-09

### Added

- Parameter to ignore specific type IRIs (blacklisting)

### Changed

- Documentation extended


## [4.2.0] 2025-10-20

### Changed

- update template and adjust tests accordingly
- ensure python 3.13 compatability
- python 3.13 required


## [4.1.0] 2025-07-17

### Changed

- upgrade dependency validators to 0.35.0


## [4.0.0] 2025-07-04

### Changed

- update template to latest develop (rdflib 7, cmem-plugin-base 4.12.0)


## [3.0.1] 2025-03-13

### Changed

- Edit warning regarding "Fetch namespace prefixes from prefix.cc" parameter

### Fixed

- Fixed error when "Properties to ignore" field is empty or contains empty lines


## [3.0.0] 2025-03-05

### Added

- Parameter to specify the label of the shapes graph. If no label is given for a new graph, a label is generated.
  - If the shapes graph exists, its label can be overwritten or kept.
- Add `dcterms:source [data graph IRI]` to the shapes graph
- Option to add plugin provenance to the shapes graph


## [2.0.1] 2025-02-19

### Changed

- Also count node shapes for the execution report
- New icon


## [2.0.0] 2025-02-10

### Added

- Add `dcterms:created` datetime for new/replaced output graphs or `dcterms:modified` datetime for updated output graphs

### Changed

- Replaced the bool parameter "Overwrite Shape Catalog" with the parameter "Handle existing output graph" with the options:
  - replace the graph
  - add the result shapes to the graph
  - stop the workflow if the specified output graph already exists
- Allow custom entries for Input data graph parameter
- Recheck if graph exists before importing created shapes graph

### Fixed

- Fixed issue with prefixes from prefix.cc not used correctly


## [1.0.0] 2025-02-03

### Added

- initial version

