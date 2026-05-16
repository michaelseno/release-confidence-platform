# Coding Standards

## Python

- Target Python 3.11.
- Use `venv` for local environments.
- Use `pyproject.toml` for dependency and tool configuration.
- Run `python -m ruff check .`, `python -m ruff format --check .`, and `python -m pytest` before commit.

## Naming

- Python modules: `snake_case` where importable.
- Domain fields: `snake_case`.
- Environment variables: uppercase `SNAKE_CASE`.
- AWS resource names: lowercase hyphenated names with stage embedded.
- Hyphenated repository folders such as `data-generation` and `report-engine` are boundaries, not importable Python package names in Phase 0.

## Testing

Phase 0 tests verify constants, sample config validity, logging standards, required structure, and infrastructure naming. Tests must not call live AWS services or execute audits.
