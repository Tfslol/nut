# Hackathon Project

This repository contains our hackathon project.

## Status

The challenge has not been released yet. Once released, requirements live in
[`docs/challenge.md`](docs/challenge.md) and take precedence over any other
assumptions in the repository.

## Development

This project uses **uv** for environment and dependency management. Do not use
`pip`, `poetry`, `pipenv`, or `conda`.

### Setup

```bash
uv sync          # install deps and create .venv (from pyproject.toml + uv.lock)
uv run pytest    # run the test suite
```

### Tooling

| Command                        | Purpose                                 |
| ------------------------------ | --------------------------------------- |
| `uv run pytest`                | Run tests (`tests/`)                    |
| `uv run ruff check .`          | Lint                                    |
| `uv run ruff format .`         | Auto-format code                        |
| `uv run ruff format --check .` | Check formatting without changing files |

### Managing dependencies

```bash
uv add <package>            # runtime dependency
uv add --group dev <pkg>    # development dependency (tests, linters)
uv remove <package>         # remove a dependency
```

When dependencies change, commit both `pyproject.toml` and `uv.lock`.

### Layout

```
src/singhacks26/   # package source (src layout)
tests/             # pytest tests
docs/challenge.md  # challenge requirements (source of truth)
docs/roles.md      # role -> label routing for collaborators/harnesses
```

### Contribution rules

Collaboration conventions (branching, PR scope, decisions, and issue
self-selection for LLM collaborators) are defined in
[`AGENTS.md`](AGENTS.md) and [`docs/roles.md`](docs/roles.md) — please read
them before making changes.