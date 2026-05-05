Builder 的 live LLM prompt 目前以内联方式维护在各个生成器中：

- `spec_generator.py`
- `case_world_generator.py`
- `character_generator.py`
- `conversation_plan_generator.py`
- `command_plan_generator.py`
- `gold_generator.py`

约束：

- 所有自然语言输出必须使用简体中文。
- `case_spec` 是最小控制对象，只允许生成 hints 和控制字段，不直接承载完整世界。
- `case_world` 才是正式企业世界对象。
- prompt 不放进 `.env`。
- `.env` 只负责模型凭证、`base_url`、`model`、`timeout`、`max_tokens` 等调用配置。
