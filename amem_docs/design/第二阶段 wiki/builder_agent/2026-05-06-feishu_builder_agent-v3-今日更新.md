# 2026-05-06 feishu_builder_agent V3 今日更新

## 1. 今天完成了什么

今天把 Task Wiki replay runtime 的 event ingestion 前半段收口成了 batch 模式。

- `session-ingest`
  已改成 `write-only + signal detection`
- `drainPendingGraphUpdates()`
  已成为唯一真正跑 extractor 的入口
- `replay runtime`
  已接到新链路，先 drain，再 verification，再 projector
- 测试
  - `pnpm test extensions/feishu-task-wiki/openclaw-lark/src/task-events/session-ingest.test.ts`
  - `python3 -m unittest discover -s feishu_builder_agent/tests -p 'test_*.py'`
  当前都已通过

## 2. 当前正式语义

当前 replay-runtime 的前半段正式语义固定为：

```text
message ingress
-> session-ingest(write-only)
-> pending_ingests / evidence_spans
-> batch drain
-> candidate_events
-> verification
-> session_events
-> projector
-> task_wiki_state
```

这里的层次已经固定：

- `pending_ingests + evidence_spans`
  是前置中间层
- `candidate_events + session_events`
  是后置中间层
- LLM extraction
  发生在 batch drain，而不是 message ingest 时

## 3. 什么时候一定会强制抽取

当前已经明确的 `hard trigger` 是：

1. `verification` 前必须 drain
2. `replay-runtime` 前必须 drain
3. `projector` 前必须 drain
4. `query / recall` 前应视为必须 drain
5. `pre-compaction` 前应视为必须 drain
6. 显式调用 `drainPendingGraphUpdates(reason=...)` 时必须消费当前 dirty span

当前已经在代码里接线的事实是：

- `runVerificationJobs(...)`
  会先调用 `drainPendingGraphUpdates(reason="verification")`
- `runtime_replay_v3.cjs`
  会在 runtime replay 和 projector 前显式调用 drain

## 4. 今天没做完 / 下一步

还没有完全收口的点如下：

- `reason` 参数虽然已经进入 drain 追踪面，但更完整的在线 query / recall 接线还没补
- `idle` 触发目前还是文档语义，尚未接成 scheduler
- `pre-compaction` 仍应补成真实接入点，当前还不能只靠文档定义
- 更多 Task Wiki 主文档还需要继续同步，避免旧文档继续描述 per-message immediate extraction
