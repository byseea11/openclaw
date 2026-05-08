# Feishu Task Wiki Benchmark Builder Skills 机制与 Agent 编排

## 文档目标

本文整理 `feishu-task-wiki-benchmark-builder` 的两套 skills 机制，以及 builder agent 如何按 Phase / Stage 编排生成、执行、回收和评测。

这里要先区分两件事：

- `.agents/skills/feishu-task-wiki-benchmark-builder` 是 Codex 侧的 skill 注册入口。
- `feishu_task_wiki_benchmark_builder/skills/*.md` 是 builder runtime 组装 prompt 时读取的 code-side skills。

这两套机制名字都叫 skill，但作用不同。

---

## 1. Codex 侧 Skill 注册

Codex 能发现 builder skill，是因为仓库里有：

- `.agents/skills/feishu-task-wiki-benchmark-builder/SKILL.md`
- `.agents/skills/feishu-task-wiki-benchmark-builder/agents/openai.yaml`

`SKILL.md` 是触发壳。

它只做三件事：

- 声明 skill 名称：`feishu-task-wiki-benchmark-builder`
- 声明什么时候应该使用这个 skill
- 要求 agent 第一时间读取 `feishu_task_wiki_benchmark_builder/skills/workflow.md`

它不承载主 workflow、family 规则、prompt 细节或 eval 口径。

`agents/openai.yaml` 是 agent profile。

它给 OpenAI/Codex 侧展示一个可选 agent：

```yaml
display_name: Feishu Task Wiki Builder
short_description: Implement the family-first Feishu Task Wiki benchmark builder
default_prompt: Use $feishu-task-wiki-benchmark-builder ...
```

所以 builder agent 的“注册位置”是：

```text
.agents/skills/feishu-task-wiki-benchmark-builder/SKILL.md
└── agents/openai.yaml
```

这只是 Codex agent 发现和启动时的入口，不是 OpenClaw runtime 的插件注册，也不是 builder runtime 的 prompt source。

---

## 2. Runtime Code-side Skills

builder 真正运行时读取的是：

```text
feishu_task_wiki_benchmark_builder/skills/
```

核心入口是：

- `feishu_task_wiki_benchmark_builder/skills/workflow.md`

它负责：

- 定义 canonical workflow
- 定义 stage routing
- 说明每个阶段应引用哪些 skill
- 声明全局 invariants

其他 `skills/*.md` 是更细的 stage / family guidance：

- stage skills：`spec-generation.md`、`conversation-plan.md`、`evaluation.md`、`runtime-eval.md` 等
- family context skills：`anti-interference-context.md`、`contradiction-update-context.md`、`evidence-dependency-context.md`、`private-info-official-file-context.md`

路径常量在：

- `feishu_task_wiki_benchmark_builder/config.py`

关键常量是：

```python
SKILLS_DIR = Path("feishu_task_wiki_benchmark_builder/skills")
WORKFLOW_SKILL = SKILLS_DIR / "workflow.md"
```

因此 runtime skill 的来源不是 `.agents/skills/...`，而是 builder package 自己的 `skills/` 目录。

---

## 3. Skill 加载机制

运行时 prompt 组装入口是：

- `feishu_task_wiki_benchmark_builder/prompt_loader.py`

核心函数有两个：

- `list_stage_prompt_sources(stage, family_id=None)`
- `build_stage_system_prompt(stage, family_id=None, difficulty=None)`

`list_stage_prompt_sources(...)` 负责决定当前阶段需要加载哪些 skill 文件。

示例：

```text
conversation-plan
-> workflow.md
-> conversation-plan.md
-> 当前 family 对应的 *-context.md
```

```text
semantic-gold
-> workflow.md
-> evaluation.md
-> 当前 family 对应的 *-context.md
```

`build_stage_system_prompt(...)` 负责把这些文件读入 system prompt。它会在 prompt 里写明来源：

```text
## Skill Source: feishu_task_wiki_benchmark_builder/skills/workflow.md
...
## Skill Source: feishu_task_wiki_benchmark_builder/skills/conversation-plan.md
...
```

然后再追加 `builder_settings.yml` 渲染出来的数字控制面，例如 difficulty、最小 turn 数、最小角色数和 family-specific minima。

这意味着：

- semantic 规则来自 `skills/*.md`
- 数字规模来自 `builder_settings.yml`
- prompt 由 `prompt_loader.py` 统一组装
- runtime 不读取 `docs/`
- runtime 不读取 `.agents/skills/...`

---

## 4. Stage 到 Skill 的映射

当前主要 runtime skill 映射如下。

| Stage               | Skill Sources                                                                                                      | 作用                                                 |
| ------------------- | ------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------- |
| `spec-generation`   | `workflow.md`、`spec-generation.md`、`family-selection.md`、`capability-brief.md`、`case-world.md`、family context | 生成 case control 和 `input/case_context.json`       |
| `task-actor-layout` | `workflow.md`、`task-actor-layout.md`                                                                              | 定义 actor roster / shared actors / context identity |
| `case-world`        | `workflow.md`、`case-world.md`                                                                                     | 定义企业世界和 source sessions                       |
| `story-beats`       | `workflow.md`、`story-beats.md`                                                                                    | 固定关键 evidence beats 和 official file plan        |
| `conversation-plan` | `workflow.md`、`conversation-plan.md`、family context                                                              | 生成完整企业 transcript                              |
| `semantic-gold`     | `workflow.md`、`evaluation.md`、family context                                                                     | 基于 observed messages 生成可选语义 gold             |
| `comparative-score` | `workflow.md`、`evaluation.md`、`runtime-eval.md`、family context                                                  | 汇总 Task Wiki 与 baseline 的比较分                  |

另外还有一个内部 scaffold：

- `feishu_task_wiki_benchmark_builder/stages/story_plan.py`

它不是公开 CLI stage，但会生成 `input/story_plan.json`，供多个细分 stage 派生结构化 artifact。

它手动加载：

```text
workflow.md
task-actor-layout.md
case-world.md
state-trajectory.md
coverage-spec.md
story-beats.md
conversation-plan.md
当前 family context skill
```

所以当前实现里存在一个重要边界：

- 公开 workflow 不再暴露旧的 `case-context` / `story-plan` 聚合 stage。
- 代码内部仍有 `case-context` 和 `story-plan` 这两个模型调用标签，用于产出 `case_context.json` 和内部 `story_plan.json`。
- 对外理解时，应以 `spec-generation -> ... -> conversation-plan` 这条细分 workflow 为准。

---

## 5. Agent 编排总览

builder agent 不是多个常驻进程。

它更像一个 stage orchestrator：

```text
Codex skill shell
-> load workflow.md
-> builder CLI / Python stage runner
-> code-side skills 组装 prompt
-> model / deterministic stage
-> artifact checkpoint
-> next stage
```

三层职责如下：

| 层                   | 位置                                                | 职责                                                              |
| -------------------- | --------------------------------------------------- | ----------------------------------------------------------------- |
| Codex agent shell    | `.agents/skills/feishu-task-wiki-benchmark-builder` | 让 Codex 知道什么时候使用 builder workflow                        |
| Builder orchestrator | `feishu_task_wiki_benchmark_builder/cli.py`         | 编排 Phase 1 / 2 / 3 stage 顺序、resume、失败记录和 artifact 写入 |
| Runtime skill loader | `prompt_loader.py`、`stages/*`                      | 为需要模型的阶段加载 skills、调用模型、验证 JSON payload          |

---

## 6. Phase 编排

### Phase 1

Phase 1 负责生成可真实执行、可回收、可 replay 的数据。

主链路是：

```text
spec-generation
-> family-selection
-> capability-brief
-> task-actor-layout
-> case-world
-> characters
-> state-trajectory
-> coverage-spec
-> story-beats
-> conversation-plan
-> command-plan
-> execute
-> collect
-> pre-annotation-validate
```

`compile_phase1(...)` 会：

- 先跑 `spec-generation`
- 按 `PHASE1_STAGE_ORDER` 继续跑后续 stage
- 对每个 stage 做 resume 判断
- 写 `runtime/builder_runs/latest.json`
- 失败时写 `runtime/failures/phase1/*`

Phase 1 中，模型主要负责：

- `case-context` 模型调用：服务公开 `spec-generation`
- `story-plan` 内部模型调用：生成可派生的中间结构
- `conversation-plan` 模型调用：生成完整企业 transcript

其他 stage 多数是 deterministic projection、schema validation、真实执行或真实回收。

### Phase 2

Phase 2 负责 gold、query 和 replay eval。

主链路是：

```text
annotation-gold
-> semantic-gold
-> query-benchmark
-> build-checks
-> gold-validate
-> replay-runtime
-> replay-eval
```

其中：

- `annotation-gold` 是 deterministic evidence gold，只基于 observed messages。
- `semantic-gold` 是可选 LLM gold，只能引用 observed `message_id`。
- `query-benchmark` 和 `replay-eval` 不应该读取 planned-only 文本作为证据。

### Phase 3

Phase 3 负责真实 runtime 对比。

主链路是：

```text
task-wiki-runtime-eval
-> openclaw-real-baseline-eval
-> comparative-score
```

正式评分产物是：

- `reports/phase3_score.json`

其中：

- `task-wiki-runtime-eval` 走真实 `task_wiki_3_layer`
- `openclaw-real-baseline-eval` 走真实 OpenClaw replay seam
- `comparative-score` 汇总 answer correctness 和 evidence correctness

---

## 7. 模型调用与日志

模型后端在：

- `feishu_task_wiki_benchmark_builder/llm.py`

默认真实模型配置只读 repo 根 `.env`：

- `OPENAI_API_KEY`
- `OPENAI_API_BASE_URL`
- `FEISHU_BUILDER_MODEL`

认证预检入口是：

- `auth-check`
- `preflight_model_backend()`

模型调用日志写入：

```text
logs/model_call_log.jsonl
```

每条日志记录 metadata：

- `timestamp`
- `stage`
- `backend`
- `model`
- `base_url`
- `success`
- `duration_ms`
- `case_id`
- `artifact_path`
- failure 时的 `error_type` / `error_code` / `message`

当前日志不记录完整 prompt 或 payload 全文。

由于 system prompt 里会包含 `## Skill Source: ...`，理论上可以从 prompt 组装逻辑推导当前 stage 使用了哪些 skill；但如果要让“skills 在哪里使用、做什么、加载了哪些文件”成为显式审计日志，更合适的挂点是：

```text
prompt_loader.list_stage_prompt_sources(...)
-> resolve skill paths
-> 写 skill usage metadata
```

推荐日志字段：

- `timestamp`
- `stage`
- `family_id`
- `difficulty`
- `skill_sources`
- `usage_purpose`
- `case_id`
- `artifact_path`

这样可以只记录 metadata，不记录 prompt 正文，避免日志膨胀和敏感内容泄露。

---

## 8. 关键边界

- `.agents/skills/...` 只负责 Codex 发现 builder skill。
- `feishu_task_wiki_benchmark_builder/skills/*.md` 才是 runtime prompt 的语义来源。
- `workflow.md` 是 machine workflow 入口，但具体约束分散到 stage skill 和 family context skill。
- `builder_settings.yml` 只负责数字控制面，不负责语义规则。
- `docs/` 是人读说明，不是 runtime prompt source。
- 真实执行只发生在 `execute` stage；`command-plan` 只生成 action rows。
- `collect` 必须基于真实 fetch 结果，不允许用 planned message 伪造 observed data。
- Phase 2 / 3 只信 observed data 和 runtime 输出，不把 builder 的计划文本当作最终证据。
