# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/) and this project adheres to [Semantic Versioning](https://semver.org/)


## [Unreleased] 

- Add dcterms:source [data graph IRI] to the shapes graph
- When adding to existing graph the source graph IRI is appended to the label. If the original label does not conform
to the format "Shapes for: [IRI], [IRI2], ..." it is prefixed with "Previous label:" and a new label is added with the
new data graph IRI.

### Added

- Add dcterms:source and plugin provenance

## [2.0.1] 2025-02-19

### Changed

- Also count node shapes for the execution report
- New icon

## [2.0.0] 2025-02-10

### Changed

- Replaced the bool parameter "Overwrite Shape Catalog" with the parameter "Handle existing output graph" with the followin options
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

### Fixed

- Fixed summary report

### Added

- Added shui:showAlways to all property shapes
- Introduced the `ignore properties` parameter to exclude specific properties from the shape graph

### Changed

- documentation


## [1.0.0beta4] 2025-01-06

- fix errors for certain namespace prefixes 


## [1.0.0beta3] 2025-01-06

- preserve multiple prefixes for one namespace in prefix.cc list


### [1.0.0beta2] 2024-12-03

- removed dependency str2bool
- use GraphParameterType for Shapes graph 


## [1.0.0beta1] 2024-07-24

### Added

- initial version

