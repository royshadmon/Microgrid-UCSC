---
name: no-git-commit-matnilm-task
description: For the MATNilm migration work, do not git commit or push to GitHub
metadata:
  type: feedback
---

During the MATNilm 2DMA migration (claude_code_prompt_matnilm_completion.md),
the user asked to drop the final commit/GitHub step from Phase 9. Do all the
phase work and verification, but leave changes in the working tree — do not run
`git add`/`git commit`/push.

**Why:** the user wants to review/manage version control themselves.
**How to apply:** complete Phase 9's verification steps (loop restart, row
checks, dashboard) but stop before any git commit.
