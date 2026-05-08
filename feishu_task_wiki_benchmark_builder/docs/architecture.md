# Feishu Task Wiki Benchmark Builder Architecture

当前实现采用三层：

- trigger shell
  - `.agents/skills/feishu-task-wiki-benchmark-builder/SKILL.md`
- control plane
  - `feishu_task_wiki_benchmark_builder/builder_settings.yml`
  - `feishu_task_wiki_benchmark_builder/builder_settings.py`
  - `feishu_task_wiki_benchmark_builder/prompt_settings_renderer.py`
- machine workflow
  - `feishu_task_wiki_benchmark_builder/skills/workflow.md`
  - `feishu_task_wiki_benchmark_builder/skills/family-selection.md`
  - `feishu_task_wiki_benchmark_builder/skills/capability-brief.md`
  - `feishu_task_wiki_benchmark_builder/skills/task-actor-layout.md`
  - `feishu_task_wiki_benchmark_builder/skills/case-world.md`
  - `feishu_task_wiki_benchmark_builder/skills/conversation-plan.md`
  - family context skills
  - `feishu_task_wiki_benchmark_builder/skills/evaluation.md`
- code executor
  - `feishu_task_wiki_benchmark_builder/cli.py`
  - `feishu_task_wiki_benchmark_builder/stages/*`

## 设计原则

- `workflow.md` 是入口，不再是唯一详细规则 owner。
- family/stage guidance 分散在多个 `skills/*.md` 文件。
- family-specific context guidance 由对应的 `*-context.md` skill 承担。
- runtime prompt 由代码从 `skills/*.md` 组装。
- `builder_settings.yml` 只负责数字控制面：人数、部门数、session 数、turn 数和 family numeric minima。
- `builder_settings.yml` 同时持有唯一默认难度来源：`default_difficulty`。
- `skills/*.md` 是 runtime prompt 的唯一语义 owner。
- `spec-generation` 负责 case control；`conversation-plan` 负责完整 transcript；`semantic-gold` 负责可选语义 gold。
- 真实模型模式只读取仓库根 `.env` 的 OpenAI 配置，不混用 shell env。
- `case_id` 和 `task_id` 这类标识符由代码层统一生成，不让模型自由命名。

## Phase 1 Checkpoints

Phase 1 会落这些 checkpoint：

- `case_spec.json`
- `input/case_context.json`
- `input/family_selection.json`
- `input/memory_capability_brief.json`
- `input/task_actor_layout.json`
- `input/case_world.json`
- `input/characters.json`
- `input/actor_registry.json`
- `input/state_trajectory.json`
- `input/coverage_spec.json`
- `input/story_beats.json`
- `input/official_file_plan.json`
- `input/conversation_plan.json`
- `input/command_plan.jsonl`
- `runtime/executed_commands.jsonl`
- `runtime/execution_result.json`
- `data/collected_messages.jsonl`
- `data/openclaw_message_ingress.jsonl`
- `checks/pre_annotation_validation_report.json`

Phase 1 的公开 CLI 主线只接受细分 stage，不再暴露旧聚合 stage。

## Prompt Boundary

运行时 prompt 只存在于：

- `feishu_task_wiki_benchmark_builder/prompt_loader.py`
- `feishu_task_wiki_benchmark_builder/prompt.py`

当前正式 prompt 面：

- `build_conversation_plan_system_prompt()`
- `build_stage_system_prompt("semantic-gold", ...)`

它们通过 `prompt_loader.py` 从 code-side skills 组装运行时约束，并通过 `prompt_settings_renderer.py` 注入 `builder_settings.yml` 解析出的数字型槽位；运行时不读取 `docs/`，也不读取 `.agents/skills/...`。
