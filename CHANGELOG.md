# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Full public documentation set under `docs/`
- MIT `LICENSE`, `CONTRIBUTING.md`, `.env.example`
- Documentation index, architecture, MCP tools reference, Cursor integration, deployment, database schema guides

## [0.1.0] - 2026

### Added

- MCP server with stdio and HTTP (streamable) transports
- `improve_prompt` with Cursor mode resolution and context-aware improvement
- Local versioned template library with public prompt CSV import
- Usage logging and aggregation (`recall_usage`, `usage_summary`)
- Scoped user facts (`remember`, `recall_facts`)
- Pattern detection and learned templates (`detect_patterns`, `save_learned_template`)
- Activity-based model routing via LiteLLM with fallback chain
- Cursor global hooks for auto prompt improvement (`deploy/cursor/`)

[Unreleased]: https://github.com/Yann-0/ylang/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Yann-0/ylang/releases/tag/v0.1.0
