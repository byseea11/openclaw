# Graph Index V2 性能测试实验记录

## 实验信息

- **实验时间**: 2026-04-21 01:02:00
- **测试框架**: CrossDeptMemBench
- **数据集**: eval/fixtures/cross_dept_mem_bench.json
  - 样本数: 10
  - 查询数: 23
  - 查询类型分布: state(8), why(5), timeline(4), list_relation(4)

## 测试配置

### 系统配置
- Gateway: http://127.0.0.1:18789 (pid 36863)
- Agent: main
- Context Engine: memory-core (Graph Index V2 enabled)
- Graph Index Bootstrap: true
- Extract During Flush: true

### 测试参数
- Timeout: 180s
- Inter-step delay: 500ms
- Detach query context: false

## 测试 1.1: 长期记忆基准测试

### Native Variant (Baseline)
**配置**:
- Context Engine: legacy (禁用 Graph Index)
- Memory Backend: builtin

**运行命令**:
```bash
openclaw config set plugins.slots.contextEngine legacy
python eval/scripts/run_cross_dept_ablation.py \
  --input eval/fixtures/cross_dept_mem_bench.json \
  --variants native \
  --output-dir eval/reports/experiment_20260421_010200/native
```

**开始时间**:

