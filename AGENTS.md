# AGENTS.md

## Project Status

This repository is a hackathon project.

The challenge has not yet been released.

Do not invent a product, architecture, requirements, or technology
choices before the challenge specification is available.

## General Rules

- Read this file before making changes.
- Read the relevant documentation before modifying code.
- Prefer small, isolated changes.
- Do not modify unrelated files.
- Do not introduce dependencies without a reason.
- Do not rewrite working code merely for stylistic reasons.
- Do not make architectural decisions without documenting them.
- Run relevant tests and checks before completing a task.

## Git

- Never commit directly to main.
- Work on a feature branch.
- Keep commits focused.
- Do not rewrite another person's branch.
- Pull/rebase from main before opening a PR when appropriate.

## Collaboration

Before implementing a substantial feature:

1. Understand the existing architecture.
2. Check existing issues and plans.
3. Identify files and interfaces that will be affected.
4. State assumptions explicitly.
5. Implement only the requested scope.

## Roles & Issue Selection

This section is for LLM harnesses and their human collaborators working out of
this repository. It defines how a worker figures out *which task to do*.

**Self-identify first.** When you are started, you may be told who you act for
(e.g. "you are Coder A"). If you are, that is your identity. If not stated,
assume you are an unassigned helper and do NOT claim issues without a human
explicitly telling you whom you represent.

Then read `docs/roles.md` and follow its "How a worker decides what to work on"
protocol. In short:

1. Find your collaborator in the role table in `docs/roles.md`.
2. Collect the GitHub issue **labels** your role owns.
3. List **open, unassigned** issues in the origin repo that carry one of your
   labels (and are not `in-progress`).
4. Pick the oldest/highest-priority one and **assign it to yourself** before
   starting.
5. Branch as `task/<issue-id>-<slug>` from `main`, implement only that issue,
   and open a PR that references/closes it.

**Assignee is the lock.** Never begin work on an issue that is already assigned
to another collaborator, and do not grab a second issue while one you claimed is
open. The role table and label scheme are scaffolding and are filled in for real
once the challenge is released (`docs/challenge.md`).

## Python Environment

This project uses uv for Python package and environment management.

Rules:

- Use uv for all dependency management.
- Do not use pip directly.
- Do not use poetry, pipenv, or conda.
- Use `uv add <package>` to add dependencies.
- Use `uv add --dev <package>` for development dependencies.
- Use `uv remove <package>` to remove dependencies.
- Commit both `pyproject.toml` and `uv.lock` when dependencies change.
- Run `uv sync` after pulling dependency changes.
- Do not manually edit `uv.lock`.

## Challenge

The challenge specification will be added to:

docs/challenge.md

Once the challenge is released, treat that document as the
primary source of truth for requirements.

If the challenge specification conflicts with assumptions made
elsewhere in the repository, the challenge specification takes
precedence.