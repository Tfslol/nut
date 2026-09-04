# Roles & Issue Routing

This file maps each collaborator (human or LLM acting on their behalf) to a
**role**, and each role to the **GitHub issue labels** that role is responsible
for. It is the canonical reference for the question:

> "Which task should I complete?"

Answer: run the self-identification + issue-selection protocol below.

## Status

The challenge has not been released yet, so the real team roles and labels are
**TBD**. The structure below is scaffolding: roles and labels are filled in from
`docs/challenge.md` once it is available. Do not invent role assignments before
then.

---

## How a worker decides what to work on

1. **Self-identify.** You (the LLM/collaborator) are told which collaborator you
   act for (e.g. "you are Coder A") by whoever starts you. Find that name in the
   [Role table](#role-table) below.
2. **Determine your label set.** From your role's row, take the `Labels` you own.
3. **Query open issues.** List open issues in the `origin` repository
   (`Tfslol/nut`) that:
   - have **at least one of your labels**, and
   - are **unassigned** (no `assignee`), and
   - are **not** marked `in-progress`.
4. **Pick one.** Prefer the oldest, then highest `priority` if present.
5. **Claim it.** Assign the issue to yourself (your collaborator). **Assignee is
   the lock**: once assigned, other workers must treat it as taken.
   - Do not start work before the assignee is set.
   - Re-run the query after assigning — do not pick a second issue while one is
     still assigned to you and not closed.
6. **Work on a branch and integrate directly.** Create
   `task/<issue-id>-<slug>` from `main`, implement only that issue's scope,
   then merge your work back into `main` yourself, resolving any merge
   conflicts as they arise (no pull request workflow).

Conventions for commits, branches, and direct merges live in `AGENTS.md`.

---

## Role table

> Fill in real rows here once the challenge is released. Keep exactly one row per
> collaborator. `Role ID` is a short stable token the harness uses when told who
> it is acting as (e.g. `coder-a`). `Labels` are the GitHub labels that run
> should own — the harness filters open issues by these.

| Role ID | Collaborator | Domain / focus | Labels (owns) | Primary area      |
| ------- | ------------ | -------------- | ------------- | ----------------- |
| _(TBD)_ | _(TBD)_      | frontend       | `frontend`    | UI / rendering    |
| _(TBD)_ | _(TBD)_      | backend        | `backend`     | API / services    |
| _(TBD)_ | _(TBD)_      | data           | `data`        | dataset / model   |
| _(TBD)_ | _(TBD)_      | infra          | `infra`       | deploy / CI / env |

## Label scheme (scaffold)

Cross-cutting status labels used by the routing protocol regardless of role:

| Label           | Meaning                                                             |
| --------------- | ------------------------------------------------------------------- |
| `bug`           | Defect to fix                                                       |
| `enhancement`   | New feature / piece of work                                         |
| `in-progress`   | Actively being worked on (side signal; designator is the real lock) |
| `priority:high` | Handle before lower priority                                        |

Role labels (`frontend`, `backend`, `data`, `infra`, …) are added only after the
challenge defines them. New work items **must** carry at least one role label so
routing is unambiguous — `AGENTS.md` and the issue templates enforce this.

## Related

- `AGENTS.md` — self-identification & claim protocol summary + general rules.
- `docs/challenge.md` — challenge requirements (source of truth).
