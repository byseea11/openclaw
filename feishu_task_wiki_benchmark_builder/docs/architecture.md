# Builder Architecture

## 四层分工

当前 builder 采用四层分工：

- `.agents/skills/feishu-task-wiki-benchmark-builder/`
  - 可触发入口
- `feishu_task_wiki_benchmark_builder/skills/`
  - 给模型看的 machine guidance
- `feishu_task_wiki_benchmark_builder/prompt.py`
  - 运行时 prompt source
- `feishu_task_wiki_benchmark_builder/docs/`
  - 给人看的说明文档

## 正式比赛口径

当前 builder 只保留三类 formal family：

- `anti_interference`
- `contradiction_update`
- `evidence_dependency_reasoning`

其中：

- `anti_interference` 对应抗干扰测试
- `contradiction_update` 对应矛盾更新测试
- `evidence_dependency_reasoning` 对应证据验证 + 依赖传播

`效能指标验证` 继续保留在 report / evaluation 层，不作为 formal family。

## 为什么这样分层

- trigger shell 需要放在 `.agents/skills/`，这样 Codex 才能发现并触发
- 真正需要频繁修改的机器 guidance 放在代码目录 `skills/`，这样更容易跟实现一起迭代
- runtime prompt 放在代码里，避免 prompt 和代码脱节
- docs 只承担人类阅读和评审用途，避免同一份文档既给人看又给机器当输入

## 关键边界

- machine skill source 不在 `docs/`
- runtime prompt source 不在 `docs/`
- prompt 不负责解释架构
- docs 不负责运行时 prompt
- `story_plan.json` 是唯一核心中间 artifact
