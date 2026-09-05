# Hackathon Project

This repository contains our hackathon project.

## Status

SingHacks 2026 challenge released. Requirements live in
[`docs/challenge.md`](docs/challenge.md) and take precedence over any other
assumptions. The current build plan is in [`docs/PRD.md`](docs/PRD.md); the
per-coder task checklists are in `docs/roles_<index>.md`.

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
docs/challenge.md      # challenge requirements (source of truth)
docs/PRD.md            # product requirements for the current build
docs/roles_<index>.md  # per-coder ralph checklists (roles_0.md, roles_1.md, ...)
```

### Contribution rules

Collaboration conventions (branching, direct merges, and per-coder task
checklists for LLM collaborators) are defined in [`AGENTS.md`](AGENTS.md) and
`docs/roles_<index>.md` — please read them before making changes.