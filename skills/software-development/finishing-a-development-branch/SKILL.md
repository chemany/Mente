---
name: finishing-a-development-branch
description: "Mente Superpower: close out a development branch after tests pass."
version: 1.0.0
author: Mente Agent
license: MIT
metadata:
  hermes:
    tags: [git, branch, merge, pr, cleanup, superpower]
    related_skills: [verification-before-completion, using-git-worktrees, requesting-code-review]
---

# Finishing A Development Branch

Use this skill after implementation and verification are complete.

## Core rule

Verify first, then choose the integration path deliberately.

## Workflow

1. Re-run the relevant tests before branch completion.
2. Identify the base branch.
3. Present clear next-step options:
   merge locally, push/create PR, keep branch, or discard.
4. Execute the chosen path.
5. Clean up the worktree only when that path requires it.
