---
title: "Using Git Worktrees — Mente Superpower: create an isolated git worktree before substantial project work"
sidebar_label: "Using Git Worktrees"
description: "Mente Superpower: create an isolated git worktree before substantial project work"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Using Git Worktrees

Mente Superpower: create an isolated git worktree before substantial project work.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/software-development/using-git-worktrees` |
| Version | `1.0.0` |
| Author | Mente Agent |
| License | MIT |
| Tags | `git`, `worktree`, `isolation`, `workflow`, `superpower` |
| Related skills | [`brainstorming`](/user-guide/skills/bundled/software-development/software-development-brainstorming), [`writing-plans`](/user-guide/skills/bundled/software-development/software-development-writing-plans), [`finishing-a-development-branch`](/user-guide/skills/bundled/software-development/software-development-finishing-a-development-branch) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Mente loads when this skill is triggered. This is what the Mente agent sees as instructions when the skill is active.
:::

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
