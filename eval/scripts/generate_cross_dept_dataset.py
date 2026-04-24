"""Generate CrossDeptMemBench dataset using DeepSeek API.

This script generates synthetic enterprise collaboration scenarios with:
- Multi-department interactions (product, dev, ops)
- Task/approval workflows (TASK-123, AP-456)
- Long-term dependency chains (blocked_by, assigned_to)
- Temporal evolution (owner changes, status updates)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eval.cross_dept_mem_feishu import enrich_cross_dept_sample


DATASET_TEMPLATES = [
    {
        "template_id": "product_launch",
        "scenario": "跨部门产品上线审批流",
        "departments": ["product", "dev", "ops"],
        "actors": ["alice@pm", "bob@dev", "carol@ops"],
        "workflow": [
            "PM 创建任务",
            "研发评估工作量，发现需要技术审批",
            "运营提出数据迁移依赖",
            "审批通过，任务解除阻塞"
        ]
    },
    {
        "template_id": "tech_approval",
        "scenario": "技术方案审批流程",
        "departments": ["dev", "ops", "security"],
        "actors": ["bob@dev", "carol@ops", "david@security"],
        "workflow": [
            "开发提交技术方案",
            "运营审核资源需求",
            "安全审核风险评估",
            "方案通过，开始实施"
        ]
    },
    {
        "template_id": "cross_dept_collab",
        "scenario": "跨部门协同项目",
        "departments": ["product", "dev", "ops", "marketing"],
        "actors": ["alice@pm", "bob@dev", "carol@ops", "eve@marketing"],
        "workflow": [
            "产品定义需求",
            "研发拆分任务",
            "运营准备环境",
            "市场准备推广方案",
            "各部门协同完成"
        ]
    }
]


GENERATION_PROMPT = """你是一个企业协作场景数据生成器。请根据以下模板生成一个真实的企业协作对话历史。

模板信息：
- 场景：{scenario}
- 部门：{departments}
- 角色：{actors}
- 工作流：{workflow}

要求：
1. 生成 10-15 轮对话历史，时间跨度 1-2 周
2. 每轮对话包含：
   - timestamp（ISO 8601 格式）
   - actor（从 actors 列表中选择）
   - department（对应 actor 的部门）
   - content（对话内容，自然语言）
   - entities（提及的实体，格式：task:TASK-123, approval:AP-456, person:alice@pm）
   - events（发生的事件，类型：task_created, owner_changed, blocked, unblocked, approval_status_updated, stage_changed）

3. 生成 3-5 个查询问题，覆盖以下类型：
   - state：当前状态查询（"TASK-123 现在被什么阻塞了？"）
   - why：因果推理查询（"TASK-123 为什么一直没有启动？"）
   - timeline：时间演进查询（"TASK-123 经历了哪些阶段？"）
   - list_relation：关系枚举查询（"运营部门在 TASK-123 中做了什么？"）

4. 每个查询包含：
   - query_id（q1, q2, ...）
   - question（问题文本）
   - query_type（state/why/timeline/list_relation）
   - gold_answer（标准答案）
   - gold_evidence（证据索引，格式：["history[0]", "history[3]"]）
   - reasoning（推理说明）

5. 实体命名规范：
   - 任务：TASK-100, TASK-101, PROD-123, DEV-456
   - 审批：AP-100, AP-101, APPROVAL-123
   - 人员：alice@pm, bob@dev, carol@ops（使用 @ 分隔姓名和部门）

6. 事件类型：
   - task_created: 创建任务
   - owner_changed: 负责人变更
   - blocked: 任务被阻塞
   - unblocked: 任务解除阻塞
   - approval_status_updated: 审批状态更新
   - stage_changed: 阶段变更
   - next_action_set: 设置下一步行动

请以 JSON 格式输出，结构如下：
{{
  "sample_id": "cross_dept_001",
  "scenario": "...",
  "departments": [...],
  "actors": [...],
  "history": [
    {{
      "timestamp": "2026-04-01T10:00:00Z",
      "actor": "alice@pm",
      "department": "product",
      "content": "创建任务 PROD-123：Q2 新功能上线",
      "entities": ["task:PROD-123"],
      "events": [
        {{
          "type": "task_created",
          "subject": "task:PROD-123",
          "actor": "alice@pm"
        }}
      ]
    }}
  ],
  "queries": [
    {{
      "query_id": "q1",
      "question": "PROD-123 现在被什么阻塞了？",
      "query_type": "state",
      "gold_answer": "...",
      "gold_evidence": ["history[3]"],
      "reasoning": "..."
    }}
  ]
}}

只输出 JSON，不要有任何其他文字。
"""


def call_deepseek_api(prompt: str, api_key: str | None = None) -> str:
    """Call DeepSeek API to generate data."""
    if not api_key:
        # Try to get from OpenClaw config
        try:
            import subprocess
            result = subprocess.run(
                ["openclaw", "config", "get", "providers.entries.deepseek.apiKey"],
                capture_output=True,
                text=True,
                check=False
            )
            if result.returncode == 0:
                api_key = result.stdout.strip().strip('"')
        except Exception:
            pass

    if not api_key:
        api_key = os.environ.get("DEEPSEEK_API_KEY")

    if not api_key:
        raise ValueError(
            "DeepSeek API key not found. Please set DEEPSEEK_API_KEY env var "
            "or configure it in OpenClaw: openclaw config set providers.entries.deepseek.apiKey <key>"
        )

    # Call DeepSeek API using urllib
    request_data = json.dumps({
        "model": "deepseek-chat",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 4000
    }).encode('utf-8')

    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions",
        data=request_data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            data = json.loads(response.read().decode('utf-8'))
            return data["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"DeepSeek API error: {e.code} {e.read().decode('utf-8')}")


def generate_sample_from_template(
    template: dict[str, Any],
    variant_id: int,
    api_key: str | None = None
) -> dict[str, Any]:
    """Generate one sample from a template."""
    prompt = GENERATION_PROMPT.format(
        scenario=template["scenario"],
        departments=", ".join(template["departments"]),
        actors=", ".join(template["actors"]),
        workflow="\n".join(f"  {i+1}. {step}" for i, step in enumerate(template["workflow"]))
    )

    print(f"Generating sample from template '{template['template_id']}' variant {variant_id}...")
    response_text = call_deepseek_api(prompt, api_key)

    # Extract JSON from response (handle markdown code blocks)
    response_text = response_text.strip()
    if response_text.startswith("```json"):
        response_text = response_text[7:]
    if response_text.startswith("```"):
        response_text = response_text[3:]
    if response_text.endswith("```"):
        response_text = response_text[:-3]
    response_text = response_text.strip()

    try:
        sample = json.loads(response_text)
    except json.JSONDecodeError as e:
        print(f"Failed to parse JSON response: {e}")
        print(f"Response text: {response_text[:500]}...")
        raise

    # Override sample_id with template-based ID
    sample["sample_id"] = f"{template['template_id']}_v{variant_id}"

    return sample


def generate_dataset(
    output_path: str | Path,
    num_samples: int = 10,
    api_key: str | None = None
) -> None:
    """Generate full dataset."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    samples: list[dict[str, Any]] = []

    # Generate samples from templates
    variants_per_template = (num_samples + len(DATASET_TEMPLATES) - 1) // len(DATASET_TEMPLATES)

    for template in DATASET_TEMPLATES:
        for variant_id in range(1, variants_per_template + 1):
            if len(samples) >= num_samples:
                break

            try:
                sample = generate_sample_from_template(template, variant_id, api_key)
                sample = enrich_cross_dept_sample(sample)
                samples.append(sample)
                print(f"✓ Generated sample {len(samples)}/{num_samples}: {sample['sample_id']}")
            except Exception as e:
                print(f"✗ Failed to generate sample: {e}")
                continue

        if len(samples) >= num_samples:
            break

    # Save dataset
    dataset = {
        "benchmark_name": "CrossDeptMemBench",
        "version": "1.0",
        "description": "Enterprise cross-department collaboration memory benchmark",
        "num_samples": len(samples),
        "samples": samples
    }

    output_path.write_text(json.dumps(dataset, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n✓ Dataset saved to {output_path}")
    print(f"  Total samples: {len(samples)}")
    print(f"  Total queries: {sum(len(s.get('queries', [])) for s in samples)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate CrossDeptMemBench dataset")
    parser.add_argument(
        "--output",
        type=str,
        default="eval/fixtures/cross_dept_mem_bench.json",
        help="Output path for generated dataset"
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=10,
        help="Number of samples to generate (default: 10)"
    )
    parser.add_argument(
        "--api-key",
        type=str,
        help="DeepSeek API key (or set DEEPSEEK_API_KEY env var)"
    )

    args = parser.parse_args()

    generate_dataset(
        output_path=args.output,
        num_samples=args.samples,
        api_key=args.api_key
    )


if __name__ == "__main__":
    main()
