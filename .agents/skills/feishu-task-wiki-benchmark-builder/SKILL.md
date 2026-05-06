---
name: feishu-task-wiki-benchmark-builder
description: Build or refactor the Feishu Task Wiki benchmark builder. Use when Codex needs the repo-local builder workflow, and then immediately load the code-side machine guidance at feishu_task_wiki_benchmark_builder/skills/root.md before making design or implementation choices.
---

# Feishu Task Wiki Benchmark Builder

Use this skill when the task is specifically about the Feishu Task Wiki benchmark builder.

## First step

Immediately read:

- `feishu_task_wiki_benchmark_builder/skills/root.md`

## What this shell does

- It provides the trigger entrypoint.
- It tells Codex where the real machine guidance lives.
- It does not carry the main workflow, family, prompt, or eval details itself.
