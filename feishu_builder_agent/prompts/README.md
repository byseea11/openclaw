Story、character 和 timeline 的 prompt 在接入 live LLM 后统一放在这里。

V1 的强约束：

- 数据集的自然语言内容必须使用简体中文
- 允许保留英文的只有内部标识字段，例如 `case_id`、`task_id`、`person_id`
- 任何 story / characters / timeline / message content 的自然语言字段如果不是中文，都应当被视为无效输出并在 schema 校验阶段拒绝
