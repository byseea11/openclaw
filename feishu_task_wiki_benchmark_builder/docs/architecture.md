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
  - `feishu_task_wiki_benchmark_builder/skills/case-world.md`
  - `feishu_task_wiki_benchmark_builder/skills/story-plan.md`
  - `feishu_task_wiki_benchmark_builder/skills/anti-interference-context.md`
  - `feishu_task_wiki_benchmark_builder/skills/contradiction-update-context.md`
  - `feishu_task_wiki_benchmark_builder/skills/evidence-dependency-context.md`
  - `feishu_task_wiki_benchmark_builder/skills/evaluation.md`
- code executor
  - `feishu_task_wiki_benchmark_builder/cli.py`
  - `feishu_task_wiki_benchmark_builder/stages/*`

## 设计原则

- `workflow.md` 是入口，不再是唯一详细规则 owner
- family/stage guidance 分散在多个 `skills/*.md` 文件
- family-specific context guidance 由对应的 `*-context.md` skill 承担，而不是继续混在通用 `task_actor_layout` 说明里
- `workflow.md` 只保留路由、阶段摘要和最小全局 invariant，不承载完整 artifact contract 或大段 anti-splitting 清单
- “不要再拆出哪些旧 artifact” 这类 anti-regression 约束主要放在 `docs/architecture.md` 和对应阶段 skill 中
- 代码只负责执行少量 stage runner 和 checkpoint 落盘
- 不再维护分散的上游 artifact 关系
- runtime prompt 由代码从 `skills/*.md` 组装
- `builder_settings.yml` 只负责数字控制面：人数、部门数、session 数、family numeric minima
- `skills/*.md` 是 runtime prompt 的唯一语义 owner：session 类型、noise 类型、role/context/dependency/revision 语义全部在 skills 中定义
- `case-context` 会组装通用 skill + 当前或全部 family context skill；`story-plan` 会组装通用 skill + 当前 family context skill
- `case-context` / `story-plan` 在组装 prompt 时会额外注入当前 difficulty profile、family numeric minima 和 stage-specific numeric slot contract
- `case-context` 和 `story-plan` 默认由 model backend 生成，不做规则 fallback
- 真实模型模式只读取仓库根 `.env` 的 OpenAI 配置，不混用 shell env
- 进入 `case-context` / `story-plan` 前必须先通过 `auth-check` 同等探活
- `case_id`、`task_id`、`story_id` 这类标识符由代码层统一生成，不让模型自由命名

## Phase 1 最少 checkpoint

Phase 1 只保留这些正式 checkpoint：

- `input/case_context.json`
- `input/story_plan.json`
- `input/command_plan.jsonl`
- `runtime/executed_commands.jsonl`
- `data/collected_messages.jsonl`
- `data/openclaw_message_ingress.jsonl`
- `checks/pre_annotation_validation_report.json`

其中：

- `case_context.json` 取代原来分散的 family selection、capability brief、case spec、case world
- `story_plan.json` 继续作为唯一核心中间 artifact

运行时日志：

- `logs/model_call_log.jsonl`
  - 记录每次 `case-context` / `story-plan` 的 model 调用
  - 成功记录只包含 metadata：stage、backend、model、base_url、success、duration、case_id、artifact_path
  - 失败记录会额外包含 error_type、error_code、http_status、message 和 raw payload（validation failure）

## Prompt Boundary

运行时 prompt 只存在于：

- `feishu_task_wiki_benchmark_builder/prompt_loader.py`
- `feishu_task_wiki_benchmark_builder/prompt.py`

当前对外仍只保留两个 stage system prompt：

- `build_case_context_system_prompt()`
- `build_story_plan_system_prompt()`

它们通过 `prompt_loader.py` 从 code-side skills 组装运行时约束，并通过 `prompt_settings_renderer.py` 注入 `builder_settings.yml` 解析出的数字型槽位；运行时不读取 `docs/`，也不读取 `.agents/skills/...`。
