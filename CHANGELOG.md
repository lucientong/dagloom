# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-04-05

### Added

- `@node` decorator to turn Python functions into pipeline nodes
- `>>` operator for building DAG pipelines
- `Pipeline` class with DAG validation (cycle detection) and topological sort
- `ExecutionContext` for passing data and metadata between nodes
- Basic synchronous pipeline execution
- Project skeleton with PyPI publishing metadata
