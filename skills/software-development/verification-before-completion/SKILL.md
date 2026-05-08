---
name: verification-before-completion
description: "Mente Superpower: verify before claiming a task is done."
version: 1.0.0
author: Mente Agent
license: MIT
metadata:
  hermes:
    tags: [verification, testing, honesty, completion, superpower]
    related_skills: [test-driven-development, requesting-code-review, finishing-a-development-branch]
---

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
