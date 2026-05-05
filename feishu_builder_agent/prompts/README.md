Story、character 和 timeline 的 prompt 在接入 live LLM 后统一放在这里。

V1 的强约束：

- 数据集的自然语言内容必须使用简体中文
- 允许保留英文的只有内部标识字段，例如 `case_id`、`task_id`、`person_id`
- 任何 story / characters / timeline / message content 的自然语言字段如果不是中文，都应当被视为无效输出并在 schema 校验阶段拒绝

补充：

- `case_profile_catalog_system.txt` / `case_profile_catalog_user.txt`
  - 用于通过 `.env` 中的 OpenAI 兼容配置（例如 DeepSeek）生成或扩展 `case_profile_catalog.json`
  - prompt 本身不放进 `.env`
  - `.env` 只负责模型凭证、base_url、model、timeout、max_tokens
