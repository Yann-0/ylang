# Contributing to Ylang

Thank you for your interest in Ylang. This project is intentionally small in Phase 1 — every file should be understandable by one person.

## Before you start

1. Read [docs/architecture.md](docs/architecture.md) for the core design rules.
2. Read [.cursor/rules/00-project.mdc](.cursor/rules/00-project.mdc) for Phase 1 scope guardrails.
3. Open an issue for large changes before investing significant time.

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

See [docs/development.md](docs/development.md) for the full workflow.

## Pull request checklist

- [ ] Change stays within Phase 1 scope (no optimizer, provenance, hosted team features, etc.).
- [ ] Business logic lives in `src/ylang/core` or domain packages — MCP tools remain thin adapters.
- [ ] New exported symbols have docstrings.
- [ ] Tests added or updated for behavior changes.
- [ ] `ruff check .` and `pytest` pass.
- [ ] User-facing behavior changes are documented under `docs/`.

## Code style

- Python 3.12+, type hints on public APIs.
- Ruff for linting (`ruff check .`, `ruff format .`).
- Prefer small, focused diffs over broad refactors.
- No new runtime dependencies without discussion in the issue/PR.

## Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` new capability
- `fix:` bug fix
- `docs:` documentation only
- `test:` tests only
- `refactor:` code change without behavior change

## Reporting issues

Include:

- Ylang version (`python -c "import ylang; print(ylang.__version__)"`)
- Transport (`stdio` or `http`)
- Steps to reproduce
- Relevant stderr output (redact API keys and tokens)

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
