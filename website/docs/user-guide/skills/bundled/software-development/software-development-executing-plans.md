---
title: "Executing Plans — Mente Superpower: execute an approved implementation plan in verified batches"
sidebar_label: "Executing Plans"
description: "Mente Superpower: execute an approved implementation plan in verified batches"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Executing Plans

Mente Superpower: execute an approved implementation plan in verified batches.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/software-development/executing-plans` |
| Version | `1.0.0` |
| Author | Mente Agent |
| License | MIT |
| Tags | `execution`, `planning`, `workflow`, `batching`, `superpower` |
| Related skills | [`writing-plans`](/user-guide/skills/bundled/software-development/software-development-writing-plans), [`verification-before-completion`](/user-guide/skills/bundled/software-development/software-development-verification-before-completion), [`finishing-a-development-branch`](/user-guide/skills/bundled/software-development/software-development-finishing-a-development-branch) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Mente loads when this skill is triggered. This is what the Mente agent sees as instructions when the skill is active.
:::

# Executing Plans

Use this skill when a written plan already exists and implementation should follow it step by step.

## Core rule

Do not improvise around the plan unless a blocker or contradiction is found.

## Workflow

1. Read the plan critically before changing code.
2. Execute a small batch of tasks in order.
3. Run the verification listed in the plan for each batch.
4. Report progress at checkpoints instead of silently drifting scope.
5. When all plan work is done, hand off to `finishing-a-development-branch`.
