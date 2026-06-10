# Memory Folder

`memory/` — a small store of persistent project notes: decisions the team has already made, conventions to apply when working on specific tasks, and reminders that should outlive any single conversation or pull request. Each note is a self-contained markdown file with YAML front-matter, and `MEMORY.md` is the index that links them together.

```
memory/
├── MEMORY.md                          # index — one bullet per note
└── no-git-commit-matnilm-task.md      # individual note
```

## Main contents

### `MEMORY.md`

The index. One bullet per note, linking to the file that holds the full text:

```markdown
- [No git commit for MATNilm task](no-git-commit-matnilm-task.md) — Phase 9: verify but do not commit/push
```

Adding a new note means appending one bullet here and creating the matching `.md` next to it.

### `no-git-commit-matnilm-task.md`

A single note. Front-matter declares its name, a one-line description, and a `metadata.type` field that classifies it (here, `feedback`):

```yaml
---
name: no-git-commit-matnilm-task
description: For the MATNilm migration work, do not git commit or push to GitHub
metadata:
  type: feedback
---
```

The body explains *what* the decision is, *why*, and *how to apply it*:

> During the MATNilm 2DMA migration, the team decided to drop the final commit/GitHub step from Phase 9. Do all the phase work and verification, but leave changes in the working tree — do not run `git add` / `git commit` / push.
>
> **Why:** the user wants to review and manage version control themselves.
>
> **How to apply:** complete Phase 9's verification steps (loop restart, row checks, dashboard) but stop before any git commit.

## Use in the project

These files exist so project-specific decisions aren't lost between sessions and aren't re-explained inside every task prompt. Conventions encoded here (no co-author trailers, terse commit messages, the user reviews and pushes their own commits) live in one place that's easy to look up.

The folder lives in the repo because the rules are about *this project specifically*. Anything tied to project conventions, recurring gotchas, or deferred decisions goes here.

## Adding a new note

1. Create `memory/<kebab-case-name>.md` with the four-line YAML front-matter (`name`, `description`, `metadata.type`).
2. Write the body as *what / why / how to apply*.
3. Append a bullet to `memory/MEMORY.md` linking it.

Types in use so far: `feedback`. Other useful types as the file count grows: `convention`, `gotcha`, `deferred-fix`.
