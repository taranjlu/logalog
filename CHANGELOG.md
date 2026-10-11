# Changelog

This file records the notable changes in each release.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

The first public release, version 1.0.0.

### Added

- The shared `LOG` object with `trace`, `debug`, `verbose`, `info`, `success`, `warning`,
  `error`, `critical`, `exception`, and `log` methods.
- Rich terminal output on stderr, with tables, syntax blocks, and other Rich renderables.
- The `plain` and `json` stderr output modes.
- Text and JSON Lines file destinations with rotation, retention, and compression.
- Live debug, verbose, and silence controls from environment variables, globally and per module.
- Configuration loading from `pyproject.toml`, TOML, JSON, and YAML files.
  YAML support needs the `yaml` extra.
- Automatic delivery: synchronous in one process, and queued for worker processes.
- Sections, the `@LOG` function decorator, and elapsed time.
- Command display with quoting and redaction. The display never runs the command.
- An optional takeover of the root handlers of the standard `logging` module.
- The public `Logger` and `Section` types for type annotations.
- Support for Python 3.11 through 3.15.
