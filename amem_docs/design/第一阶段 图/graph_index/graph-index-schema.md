# Graph Index Schema (v6)

SQLite 文件路径：`~/.openclaw/memory/{agentId}.graph.sqlite`

---

## meta

存储数据库元信息（schema 版本等）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `key` | TEXT PK | 键名，如 `schema_version` |
| `value` | TEXT | 对应的值 |

---

## graph_metrics

存储运行时统计指标（命中次数、提取延迟等）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `key` | TEXT PK | 指标名，如 `hitsReturned`、`extractSuccesses` |
| `value` | REAL | 指标数值，默认 0 |

---

## evidence_records

原始证据记录，即触发事件提取的消息/上下文片段。

| 字段 | 类型 | 说明 |
|------|------|------|
| `evidence_id` | TEXT PK | 证据唯一 ID |
| `evidence_fingerprint` | TEXT UNIQUE | 内容指纹，用于去重 |
| `source_platform` | TEXT | 来源平台，如 `telegram`、`discord` |
| `source_kind` | TEXT | 来源类型：`transcript` / `tool_result` / `flush` 等 |
| `session_key` | TEXT | 所属会话 key |
| `message_id` | TEXT | 原始消息 ID |
| `chat_id` | TEXT | 聊天/频道 ID |
| `chat_type` | TEXT | 聊天类型，如 `private`、`group` |
| `thread_id` | TEXT | 线程 ID（如有） |
| `root_id` | TEXT | 根消息 ID |
| `parent_id` | TEXT | 父消息 ID |
| `first_entry_id` | TEXT | 覆盖的第一条 transcript entry ID |
| `last_entry_id` | TEXT | 覆盖的最后一条 transcript entry ID |
| `content_text` | TEXT | 消息纯文本内容 |
| `content_json` | TEXT | 消息结构化内容（JSON），默认 `{}` |
| `source_locator_json` | TEXT | 来源定位信息（JSON），默认 `{}` |
| `occurred_at` | TEXT | 消息发生时间（ISO 8601） |
| `created_at` | INTEGER | 记录写入时间（Unix ms） |

---

## event_type_registry

已知事件类型的注册表，定义每种事件的主体/客体类型和 payload schema。

| 字段 | 类型 | 说明 |
|------|------|------|
| `event_type` | TEXT PK | 事件类型名，如 `task.assigned`、`decision.made` |
| `subject_type` | TEXT | 主体实体类型，如 `person`、`task` |
| `object_type` | TEXT | 客体实体类型（可为空） |
| `payload_schema_json` | TEXT | payload 的 JSON Schema 定义 |
| `description` | TEXT | 事件类型的人类可读描述 |
| `enabled` | INTEGER | 是否启用（1=是，0=否） |
| `created_at` | INTEGER | 注册时间（Unix ms） |

---

## event_records_v2

从对话中提取的结构化事件，是图谱的核心数据来源。

| 字段 | 类型 | 说明 |
|------|------|------|
| `event_id` | TEXT PK | 事件唯一 ID |
| `event_fingerprint` | TEXT UNIQUE | 事件内容指纹，用于去重 |
| `evidence_id` | TEXT FK→evidence_records | 关联的原始证据 ID |
| `event_type` | TEXT FK→event_type_registry | 事件类型 |
| `subject_ref` | TEXT | 事件主体的实体引用（entity_ref 格式） |
| `actor_ref` | TEXT | 执行动作的人/系统的实体引用（可为空） |
| `object_ref` | TEXT | 事件客体的实体引用（可为空） |
| `related_refs_json` | TEXT | 其他相关实体引用列表（JSON 数组），默认 `[]` |
| `occurred_at` | TEXT | 事件发生时间（ISO 8601） |
| `payload_json` | TEXT | 事件附加数据（JSON），默认 `{}` |
| `confidence` | REAL | 提取置信度 0.0~1.0，默认 0.5 |
| `extraction_version` | TEXT | 提取器版本，如 `v1-2026.04-llm` |
| `created_at` | INTEGER | 记录写入时间（Unix ms） |

---

## graph_entities_v2

图谱中的实体节点（人、任务、项目、决策等）。

| 字段 | 类型 | 说明 |
|------|------|------|
| `entity_ref` | TEXT PK | 实体唯一引用，格式如 `person:alice` |
| `entity_type` | TEXT | 实体类型：`person` / `team` / `project` / `task` / `decision` / `document` / `meeting` / `customer` / `other` |
| `canonical_name` | TEXT | 实体的规范名称，如 `Alice` |
| `alias_json` | TEXT | 别名列表（JSON 数组），默认 `[]` |
| `first_seen_at` | TEXT | 首次出现时间（ISO 8601） |
| `last_seen_at` | TEXT | 最近出现时间（ISO 8601） |
| `last_evidence_id` | TEXT | 最近一次关联的证据 ID |
| `updated_at` | INTEGER | 记录最后更新时间（Unix ms） |

---

## graph_edges_v2

实体之间的关系边。

| 字段 | 类型 | 说明 |
|------|------|------|
| `edge_id` | TEXT PK | 边唯一 ID |
| `edge_key` | TEXT UNIQUE | 边的去重 key（src+type+dst 的组合） |
| `src_ref` | TEXT | 源实体引用（entity_ref） |
| `edge_type` | TEXT | 关系类型：强关系如 `assigned_to`、`depends_on`、`blocks`；弱关系如 `about`、`mentions`、`related_to` |
| `dst_ref` | TEXT | 目标实体引用（entity_ref） |
| `derived_from_event_id` | TEXT FK→event_records_v2 | 推导出此边的事件 ID |
| `active` | INTEGER | 是否当前有效（1=是，0=已失效） |
| `valid_from` | TEXT | 关系生效时间（ISO 8601） |
| `valid_to` | TEXT | 关系失效时间（ISO 8601，可为空表示仍有效） |
| `updated_at` | INTEGER | 记录最后更新时间（Unix ms） |

---

## workflow_state_view_v2

任务/工作流的当前状态视图，由事件流聚合而来。

| 字段 | 类型 | 说明 |
|------|------|------|
| `task_ref` | TEXT PK | 任务实体引用（entity_ref） |
| `current_owner_ref` | TEXT | 当前负责人的实体引用 |
| `current_stage` | TEXT | 当前阶段，如 `in_progress`、`review`、`done` |
| `current_approval_ref` | TEXT | 当前审批人的实体引用 |
| `approval_status` | TEXT | 审批状态：`unknown` / `pending` / `approved` / `rejected` / `needs_review` |
| `current_blocker_ref` | TEXT | 当前阻塞项的实体引用 |
| `next_action_json` | TEXT | 下一步行动描述（JSON），默认 `{}` |
| `last_event_id` | TEXT FK→event_records_v2 | 最后一次更新此状态的事件 ID |
| `last_event_time` | TEXT | 最后事件时间（ISO 8601） |
| `slot_versions_json` | TEXT | 各字段的版本号（用于冲突检测，JSON），默认 `{}` |
| `supporting_event_ids` | TEXT | 支撑此状态的事件 ID 列表（JSON 数组），默认 `[]` |
| `updated_at` | INTEGER | 记录最后更新时间（Unix ms） |

---

## source_projection_state

记录每个数据源的 projection 进度，避免重复处理。

| 字段 | 类型 | 说明 |
|------|------|------|
| `source_kind` | TEXT PK | 来源类型，目前为 `transcript` |
| `source_id` | TEXT PK | 来源 ID（如 session key） |
| `covered_until_entry_id` | TEXT | 已处理到的最后一条 entry ID |
| `dirty_since_entry_id` | TEXT | 从哪条 entry 开始需要重新处理 |
| `last_projected_at` | INTEGER | 上次 projection 完成时间（Unix ms） |
| `projection_version` | TEXT | projection 算法版本，如 `v1-2026.04` |
| `status` | TEXT | 状态：`clean` / `dirty` / `draining` / `failed` |

---

## projection_inbox

待处理的 projection 任务队列，新消息到来时写入此表。

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | INTEGER PK AUTOINCREMENT | 自增主键 |
| `source_kind` | TEXT | 来源类型 |
| `source_id` | TEXT | 来源 ID |
| `first_entry_id` | TEXT | 批次中第一条 entry ID |
| `last_entry_id` | TEXT | 批次中最后一条 entry ID |
| `entries_json` | TEXT | 待处理的 entry 列表（JSON） |
| `dirty_reason` | TEXT | 触发原因，如 `new_message`、`flush` |
| `signal_strength` | REAL | 信号强度（影响处理优先级），默认 0 |
| `strong_event` | INTEGER | 是否包含强信号事件（1=是），默认 0 |
| `created_at` | INTEGER | 入队时间（Unix ms） |
| `drained_at` | INTEGER | 处理完成时间（Unix ms，null 表示待处理） |

---

## recent_graph_hits

最近返回给 LLM 的图谱命中缓存，用于去重和使用率追踪。

| 字段 | 类型 | 说明 |
|------|------|------|
| `session_key` | TEXT PK | 会话 key |
| `source_ref` | TEXT PK | 来源引用（文件路径+行号） |
| `path` | TEXT PK | 文件路径 |
| `start_line` | INTEGER PK | 起始行号 |
| `end_line` | INTEGER PK | 结束行号 |
| `hit_type` | TEXT PK | 命中类型：`event` / `state` / `edge` |
| `entity_id` | TEXT | 关联的实体 ID |
| `query` | TEXT | 触发此命中的查询内容 |
| `first_returned_at` | INTEGER | 首次返回时间（Unix ms） |
| `last_returned_at` | INTEGER | 最近返回时间（Unix ms） |
| `expires_at` | INTEGER | 过期时间（Unix ms，默认 30 分钟 TTL） |
| `used_at` | INTEGER | LLM 实际使用此命中的时间（Unix ms，null 表示未使用） |
