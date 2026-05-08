---
title: "Finishing A Development Branch — Mente Superpower: close out a development branch after tests pass"
sidebar_label: "Finishing A Development Branch"
description: "Mente Superpower: close out a development branch after tests pass"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Finishing A Development Branch

Mente Superpower: close out a development branch after tests pass.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/software-development/finishing-a-development-branch` |
| Version | `1.0.0` |
| Author | Mente Agent |
| License | MIT |
| Tags | `git`, `branch`, `merge`, `pr`, `cleanup`, `superpower` |
| Related skills | [`verification-before-completion`](/user-guide/skills/bundled/software-development/software-development-verification-before-completion), [`using-git-worktrees`](/user-guide/skills/bundled/software-development/software-development-using-git-worktrees), [`requesting-code-review`](/user-guide/skills/bundled/software-development/software-development-requesting-code-review) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Mente loads when this skill is triggered. This is what the Mente agent sees as instructions when the skill is active.
:::

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
