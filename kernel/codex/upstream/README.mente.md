# Mente Notes For Vendored Upstream Codex Snapshot

This directory is **vendored upstream source** from `https://github.com/openai/codex`.
It is **not Mente-authored kernel code**.

## Snapshot

- Upstream repository: `https://github.com/openai/codex`
- Pinned snapshot identifier: `8f3c06cc97bbb045fe5790a6388625c0db35af7f`
- Ingested by Mente on: `2026-04-30`

## Local Edit Policy

- Default policy: no local edits inside the vendored upstream tree.
- Allowed exception: only strictly necessary changes for basic import safety.
- Current local edits: none.
- If a future local edit is unavoidable, record the file path, reason, and diff summary here.

## Ownership Boundary

- This snapshot stays recognizable as upstream Codex source.
- Thin Mente bridge code belongs outside this tree.
- Mente product/runtime concerns remain in `mente/`.
