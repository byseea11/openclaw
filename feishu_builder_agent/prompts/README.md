Builder 的 prompt 现在统一集中维护在 `feishu_builder_agent/prompt_templates.py`，不再以内联方式散落在各个生成器里。

当前主要入口：

- `build_spec_prompts(...)`
- `build_case_world_prompts(...)`
- `build_character_prompts(...)`
- `build_conversation_plan_prompts(...)`
- `build_command_plan_prompts(...)`
- `build_gold_event_prompts(...)`
- `build_story_prompts(...)`
- `build_timeline_prompts(...)`
- `build_utterance_plan_prompts(...)`
- `build_message_realizer_prompts(...)`

约束边界：

- `feishu_builder_agent/builder_settings.yml` 是数量约束、复杂度目标、部门池的唯一配置来源。
- `spec / case-world / characters / plan` 四个结构层阶段会把难度目标直接注入 live prompt。
- 所有自然语言输出必须使用简体中文。
- `case_spec` 是最小控制对象，只允许生成 hints 和控制字段，不直接承载完整世界。
- `case_world` 是 canonical world，后续 `characters / conversation_plan / gold` 都以它为准。
- prompt 不放进 `.env`。
- `.env` 只负责模型调用配置，例如 `base_url`、`model`、`timeout`、`max_tokens`。

`conversation_plan` 阶段当前采用二段式 live 生成链：

1. 第一次 live 生成
2. 静态计算 metrics 和 remaining deficit
3. 第二次 live retry，把 deficit 显式注入 prompt
4. 如果 retry 仍然非法或不足，再进入显式 `fallback + deterministic repair`

完整轨迹会写入：

- `checks/conversation_plan_generation_log.json`

因此 fallback 不是 silent fallback，而是可审计的 degraded 路径。
