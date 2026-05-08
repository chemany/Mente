---
name: using-git-worktrees
description: "Mente Superpower: create an isolated git worktree before substantial project work."
version: 1.0.0
author: Mente Agent
license: MIT
metadata:
  hermes:
    tags: [git, worktree, isolation, workflow, superpower]
    related_skills: [brainstorming, writing-plans, finishing-a-development-branch]
---

# Using Git Worktrees

Use this skill when a project task should be isolated from the current checkout.

## Core rule

Prefer a separate worktree for multi-step feature work, risky refactors, or branch-specific implementation.

## Workflow

1. Detect whether `.worktrees/` or `worktrees/` already exists.
2. Verify the chosen directory is ignored when it lives inside the repo.
3. Create a new worktree on a dedicated branch.
4. Run project setup in the new worktree.
5. Verify a clean baseline before implementation starts.

## Safety checks

- Never create a project-local worktree without confirming it is ignored.
- Never proceed with a failing baseline without surfacing that to the user.
