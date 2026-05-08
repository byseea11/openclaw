# CrossDeptMem 测试框架使用指南

## 概述

CrossDeptMem 是专门为测试 Graph Index V2 在企业跨部门协作场景下性能提升而设计的测试框架。

## 已完成的组件

### 1. 数据集生成脚本
**文件**: `eval/scripts/generate_cross_dept_dataset.py`

使用 DeepSeek API 生成企业协作场景的模拟数据：
- 3 个核心模板（产品上线、技术审批、跨部门协同）
- 每个样本包含 10-15 轮语义 history，并自动升级为 Feishu-like raw messages
- 每个样本包含 3-5 个查询问题（state/why/timeline/list_relation）

**使用方法**:
```bash
# 设置 DeepSeek API key
export DEEPSEEK_API_KEY="your-api-key"

# 生成 8 个样本
python eval/scripts/generate_cross_dept_dataset.py \
  --output eval/fixtures/cross_dept_mem_bench.json \
  --samples 8
```

### 2. Adapter
**文件**: `eval/adapters/cross_dept_mem.py`

将 CrossDeptMem 数据集转换为 OpenClaw 输入格式：
- `build_history_inputs()`: 优先使用 `messages` 里的 Feishu-like raw chat，兼容旧 `history`
- `build_query_input_for_query()`: 构建查询步骤（支持多查询）
- `parse_prediction()`: 解析模型响应

### 2.5 数据升级脚本
**文件**: `eval/scripts/upgrade_cross_dept_dataset_to_feishu.py`

把旧版只有 `history` 的 fixture 升级成双层结构：
- `messages` / `chat`: 更像 Feishu 的 raw message layer
- `history` / `queries`: 继续作为 gold semantic layer

**使用方法**:
```bash
python eval/scripts/upgrade_cross_dept_dataset_to_feishu.py \
  --input eval/fixtures/cross_dept_mem_bench.json
```

### 3. Scorer
**文件**: `eval/scorers/cross_dept_mem.py`

计算评估指标：
- `exact_match`: 精确匹配率
- `average_f1`: 平均 F1 分数
- `average_prompt_tokens`: 平均 prompt token 数
- `average_memory_search_calls`: 平均 memory_search 调用次数
- 按查询类型分桶统计（state/why/timeline/list_relation）

### 4. Ablation Runner
**文件**: `eval/cross_dept_mem_ablation.py` + `eval/scripts/run_cross_dept_ablation.py`

运行 native vs graph-index 对比测试：
- 支持多查询样本
- 自动计算 metric deltas
- 生成详细报告

**使用方法**:
```bash
# 运行完整 ablation 测试（native + graph）
python eval/scripts/run_cross_dept_ablation.py \
  --input eval/fixtures/cross_dept_mem_bench.json \
  --output-dir eval/reports/cross_dept_ablation \
  --inter-step-delay-ms 500

# 只运行 graph variant
python eval/scripts/run_cross_dept_ablation.py \
  --input eval/fixtures/cross_dept_mem_bench.json \
  --variants graph

# 限制样本数量（快速测试）
python eval/scripts/run_cross_dept_ablation.py \
  --input eval/fixtures/cross_dept_mem_bench.json \
  --max-samples 3
```

## 测试流程

### 步骤 1: 生成数据集
```bash
export DEEPSEEK_API_KEY="sk-..."
python eval/scripts/generate_cross_dept_dataset.py \
  --output eval/fixtures/cross_dept_mem_bench.json \
  --samples 8
```

### 步骤 2: 配置 OpenClaw
确保 memory-core context engine 已启用：
```bash
openclaw config set plugins.slots.contextEngine memory-core
openclaw config set plugins.entries.memory-core.config.graphIndex.enabled true
```

### 步骤 3: 运行测试
```bash
# 运行 native vs graph 对比测试
python eval/scripts/run_cross_dept_ablation.py \
  --input eval/fixtures/cross_dept_mem_bench.json \
  --output-dir eval/reports/cross_dept_ablation_$(date +%Y%m%d)
```

### 步骤 4: 查看结果
```bash
# 查看对比报告
cat eval/reports/cross_dept_ablation_*/comparison.json | jq .

# 查看详细输出
cat eval/reports/cross_dept_ablation_*/native.details.json | jq .
cat eval/reports/cross_dept_ablation_*/graph.details.json | jq .
```

## 预期结果

根据 plan.md 的预期，Graph Index V2 应该在以下方面有显著提升：

### 长期记忆性能（测试 1.1）
- `exact_match`: +20-30%（状态查询）
- `f1`: +15-25%（因果推理）
- `prompt_tokens`: -50-70%（结构化投影）
- `latency_ms`: -30-50%（减少工具调用）

### 工具调用效率（测试 2.1, 2.2）
- `memory_search_calls`: -60-80%（assemble-time recall）
- `tool_call_success_rate`: +20-30%（更好的 evidence ordering）

## 数据集结构

CrossDeptMem 现在是一个双层结构：

- `messages/chat/platform`: Feishu-like raw 输入层
- `history/queries`: semantic gold 层，继续给 scorer / evidence 标注使用

这意味着它比旧版更接近 Feishu 群聊结构，但仍然是**合成数据**，不是从真实 Feishu 导出的日志。

```json
{
  "benchmark_name": "CrossDeptMemBench",
  "version": "1.0",
  "samples": [
    {
      "sample_id": "product_launch_v1",
      "platform": "feishu",
      "chat": {
        "chat_id": "oc_product_launch_v1",
        "chat_type": "group",
        "chat_name": "跨部门产品上线审批流"
      },
      "scenario": "跨部门产品上线审批流",
      "departments": ["product", "dev", "ops"],
      "actors": ["alice@pm", "bob@dev", "carol@ops"],
      "messages": [
        {
          "message_id": "om_product_launch_v1_001",
          "chat_id": "oc_product_launch_v1",
          "chat_type": "group",
          "thread_id": "omt_product_launch_v1_task_prod_123",
          "root_id": "om_product_launch_v1_001",
          "parent_id": null,
          "created_at": "2026-04-01T10:00:00Z",
          "message_type": "post",
          "sender": {
            "open_id": "ou_alice_pm",
            "display_name": "Alice",
            "department": "product",
            "actor_ref": "alice@pm"
          },
          "mentions": [],
          "content_text": "创建任务 PROD-123：Q2 新功能上线",
          "content_json": {
            "title": "协作更新",
            "body": "创建任务 PROD-123：Q2 新功能上线"
          }
        }
      ],
      "history": [
        {
          "timestamp": "2026-04-01T10:00:00Z",
          "actor": "alice@pm",
          "department": "product",
          "content": "创建任务 PROD-123：Q2 新功能上线",
          "entities": ["task:PROD-123"],
          "events": [
            {
              "type": "task_created",
              "subject": "task:PROD-123",
              "actor": "alice@pm"
            }
          ]
        }
      ],
      "queries": [
        {
          "query_id": "q1",
          "question": "PROD-123 现在被什么阻塞了？",
          "query_type": "state",
          "gold_answer": "...",
          "gold_evidence": ["history[3]"],
          "reasoning": "..."
        }
      ]
    }
  ]
}
```

### 为什么保留 `history`

因为当前 scorer 仍然依赖：
- `queries[*].gold_answer`
- `queries[*].gold_evidence`
- `history[*].events`

所以 `history` 现在不是 runtime 输入主层，而是 gold semantic 标注层。

### 当前 realism 边界

这次升级解决的是“字段和输入形态太不像 Feishu”的问题，但它仍然不是完整真实 Feishu 语料，当前限制包括：

- `content_text` 仍然是合成文本，不是真实员工群聊口语
- `mentions` 还比较少，没有充分覆盖 @人 / reply / bot card
- `message_type` 目前只做了轻量映射（`text/post/interactive`）
- 没有真实文件、文档分享、机器人通知、已读/撤回等平台噪音

所以它更适合叫：

- “Feishu-like synthetic benchmark”

而不是：

- “真实 Feishu 日志 benchmark”

## 故障排查

### 数据生成失败
- 检查 DeepSeek API key 是否正确
- 检查网络连接
- 查看错误日志

### 测试运行失败
- 确保 OpenClaw gateway 正在运行: `openclaw gateway status`
- 确保 memory-core context engine 已启用
- 检查数据集文件是否存在

### 结果异常
- 检查 `inter-step-delay-ms` 是否足够（建议 500ms）
- 检查 graph index 是否已 bootstrap
- 查看 gateway 日志: `tail -f /tmp/openclaw/openclaw-*.log`

## 下一步

1. 等待数据生成完成
2. 运行完整 ablation 测试
3. 分析结果，生成性能报告
4. 根据结果调整 graph index 参数
5. 补充更多测试场景（时间冲突、信息断层等）

## 相关文件

- 计划文档: `/Users/byseea/.claude/plans/expressive-inventing-wigderson.md`
- 数据集: `eval/fixtures/cross_dept_mem_bench.json`
- 升级脚本: `eval/scripts/upgrade_cross_dept_dataset_to_feishu.py`
- Adapter: `eval/adapters/cross_dept_mem.py`
- Scorer: `eval/scorers/cross_dept_mem.py`
- Ablation Runner: `eval/cross_dept_mem_ablation.py`
- 测试脚本: `eval/scripts/run_cross_dept_ablation.py`
- 数据生成脚本: `eval/scripts/generate_cross_dept_dataset.py`
