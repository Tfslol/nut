# ralph working folder

Ralph is the multi-coder build loop that turns `docs/PRD.md` into code. Each
coder (Role 0, Role 1, ...) executes one tracked markdown checklist:

- `docs/roles_0.md`
- `docs/roles_1.md`

This folder is the git-tracked scratch/workspace for Ralph artefacts that do
not belong in `src/`, `docs/`, or the Obsidian vault (for example draft
payloads, API response samples, and generated cache samples created while
working a role checklist).
