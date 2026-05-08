---
name: executing-plans
description: "Mente Superpower: execute an approved implementation plan in verified batches."
version: 1.0.0
author: Mente Agent
license: MIT
metadata:
  hermes:
    tags: [execution, planning, workflow, batching, superpower]
    related_skills: [writing-plans, verification-before-completion, finishing-a-development-branch]
---

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
