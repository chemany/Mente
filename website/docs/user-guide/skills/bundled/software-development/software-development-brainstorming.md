---
title: "Brainstorming — Mente Superpower: clarify project intent and design before implementation"
sidebar_label: "Brainstorming"
description: "Mente Superpower: clarify project intent and design before implementation"
---

{/* This page is auto-generated from the skill's SKILL.md by website/scripts/generate-skill-docs.py. Edit the source SKILL.md, not this page. */}

# Brainstorming

Mente Superpower: clarify project intent and design before implementation.

## Skill metadata

| | |
|---|---|
| Source | Bundled (installed by default) |
| Path | `skills/software-development/brainstorming` |
| Version | `1.0.0` |
| Author | Mente Agent |
| License | MIT |
| Tags | `planning`, `design`, `discovery`, `project-development`, `superpower` |
| Related skills | [`using-git-worktrees`](/user-guide/skills/bundled/software-development/software-development-using-git-worktrees), [`writing-plans`](/user-guide/skills/bundled/software-development/software-development-writing-plans), [`test-driven-development`](/user-guide/skills/bundled/software-development/software-development-test-driven-development) |

## Reference: full SKILL.md

:::info
The following is the complete skill definition that Mente loads when this skill is triggered. This is what the Mente agent sees as instructions when the skill is active.
:::

# Brainstorming

Use this skill before building features, changing behavior, or designing a new project slice.

## Core rule

Do not jump straight into code when the task needs product or engineering design choices.

## Workflow

1. Inspect the current project context first.
2. Clarify the task goal, constraints, and acceptance criteria.
3. Propose 2-3 approaches with tradeoffs.
4. Recommend one approach with a short reason.
5. If implementation will follow, hand off to `using-git-worktrees` and `writing-plans`.

## Output expectations

- Keep the exploration concrete.
- Prefer one question at a time when the task is underspecified.
- Write down assumptions before implementation starts.
