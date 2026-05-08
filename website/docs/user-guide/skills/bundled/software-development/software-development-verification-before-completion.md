---
title: "Verification Before Completion — Mente Superpower: verify before claiming a task is done"
sidebar_label: "Verification Before Completion"
description: "Mente Superpower: verify before claiming a task is done"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Verification Before Completion

Mente Superpower: verify before claiming a task is done.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/software-development/verification-before-completion` |
| Version | `1.0.0` |
| Author | Mente Agent |
| License | MIT |
| Tags | `verification`, `testing`, `honesty`, `completion`, `superpower` |
| Related skills | [`test-driven-development`](/user-guide/skills/bundled/software-development/software-development-test-driven-development), [`requesting-code-review`](/user-guide/skills/bundled/software-development/software-development-requesting-code-review), [`finishing-a-development-branch`](/user-guide/skills/bundled/software-development/software-development-finishing-a-development-branch) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Mente loads when this skill is triggered. This is what the Mente agent sees as instructions when the skill is active.
:::

# Verification Before Completion

Use this skill before saying a feature is fixed, complete, passing, or ready to ship.

## Core rule

No completion claim without fresh verification evidence.

## Workflow

1. Identify the command that proves the claim.
2. Run the full command now.
3. Read the output and exit status.
4. Report the real status with evidence.

## Red flags

- "Should work now"
- "Looks done"
- "Probably passes"
- Claiming success from code inspection alone
