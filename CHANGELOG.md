<!-- markdownlint-disable MD012 MD013 MD024 MD033 -->
# Change Log

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](http://keepachangelog.com/) and this project adheres to [Semantic Versioning](https://semver.org/)

## [Unreleased]

### Added

- Node and property shapes now get `sh:description` from the description Corporate Memory resolves for the class or property - its `rdfs:comment`, `dcterms:description` or `skos:definition`, wherever the class or property is defined, so descriptions from a vocabulary graph are picked up as well as those in the data graph
- Property shapes now get `sh:datatype rdf:langString` when the data graph uses the property with a language-tagged literal
- Parameter to omit the trailing namespace prefix (e.g. `(rdfs:)`) from property shape names
- Parameter to declare with `shui:managedClasses` which classes the shape catalog manages
- Parameter to import the query catalog into the shape catalog with `owl:imports`
- Parameter to add the `foaf:depiction` of a target class to its node shape, looked up in the
  data graph and in the graph named by the class namespace, with and without its trailing
  separator

### Fixed

- Shape labels and names are tagged with the language they were actually resolved in.
  They were tagged `@en` whatever came back, so a vocabulary with no English label
  produced a foreign-language label claiming to be English. A name derived from the IRI,
  which has no language, is now written without a tag

### Changed

- Updated project template to v9.7.0 (cmem-client 1.1.0, ruff 0.16.6)
- Labels and descriptions are now resolved with one batched request each instead of one
  request per class and property, so generating shapes for a large graph is faster
- Task documentation rewritten: it now says what is generated, what each shape carries, and
  the four caveats a user meets - the language a name is tagged with, one property shape
  shared by every class using that property, `sh:datatype rdf:langString` added on a single
  tagged value, and shapes accumulating when adding to an existing catalog
- Parameter descriptions and labels reworded to speak of one shape catalog throughout, to
  say what each parameter controls without repeating the dropdown, and to follow the
  eccenca Corporate Memory naming convention instead of the "CMEM" abbreviation
- The provenance option is now named after what it records - the task that generated the
  catalog, not the plugin - and says that it records nothing, without failing the run, when
  the type of the task cannot be determined
- The shape catalog label is now an advanced parameter, since leaving it empty names a new
  catalog and preserves the name of an existing one
- The choices for handling an existing catalog explain themselves in the dropdown

## [4.4.0] 2026-08-20

### Changed

- Updated template and dependencies
- Exchanged cmempy code with cmem-client usage

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

