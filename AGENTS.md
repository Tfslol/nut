# AGENTS.md

## Project Status

This repository is a SingHacks 2026 hackathon project (Julius Baer wealth
intelligence).

The challenge specification is available in `docs/challenge.md` and is the
source of truth for requirements. The current build plan and per-coder task
split live in `docs/PRD.md` and `docs/roles_<index>.md`.

Do not invent product requirements that are not grounded in the challenge or in
`docs/PRD.md`.

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
- Pull/rebase from main frequently and resolve merge conflicts directly when
  landing work (no pull requests).

## Collaboration

Before implementing a substantial feature:

1. Understand the existing architecture.
2. Check existing issues and plans.
3. Identify files and interfaces that will be affected.
4. State assumptions explicitly.
5. Implement only the requested scope.

## Roles & Task Selection

This section is for LLM harnesses and their human collaborators working out of
this repository. Future tasks are driven by per-coder checklist files rather
than GitHub issues or pull requests.

**Self-identify first.** When you are started, you may be told who you act for
(e.g. "you are Role 0" / "you are Coder A"). If so, that is your identity. If
not stated, assume you are an unassigned helper and do not begin implementation
until a human tells you which role index you represent.

Then:

1. Read `docs/PRD.md` for the product requirements the work is split from.
2. Open `docs/roles_<index>.md` for your role index (e.g. `docs/roles_0.md`).
   It is a markdown checklist owned by your role.
3. Work the checklist top to bottom. Tick an item (`- [x]`) only when it is
   genuinely complete and verified.
4. Branch as `role/<index>-<slug>` from `main`, implement only your role's
   scope, then integrate your work back to `main` yourself, resolving any merge
   conflicts directly. No pull requests, no GitHub issues, no issue assignment.

**Your role file is the plan.** Do not start items another role owns, do not
pick up extra scope, and do not rewrite another role's branch. If a shared
interface or the PRD is ambiguous, state your assumption and note it in your
role file rather than inventing silently.

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

The challenge specification lives at:

docs/challenge.md

Treat that document as the primary source of truth for requirements. Where it
conflicts with assumptions made elsewhere in the repository (including this
file and the PRD), the challenge specification takes precedence.