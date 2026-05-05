#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

PHASE="full"
CASE_SPEC="amem_docs/dataset_v1/case_specs/feishu_builder_case_example.json"
DATASET_ROOT="amem_docs/ds/feishu_im_dataset_v2"
CASE_DIR=""
DRY_RUN=0
SKIP_AUTH=0
FRESH_RUN=1

usage() {
  cat <<'EOF'
用法：
  amem_docs/scripts/feishu-builder-agent-run.sh [options]

默认行为：
  运行完整的 feishu_builder_agent 主流程，并把产物落到 amem_docs/ds：
    compile -> execute -> collect -> adapt

阶段说明：
  --phase case-world  只生成 V2 的 case_seed / case_world
  --phase plan        只生成 V2 的 conversation_plan
  --phase utterance   只生成 V2 的 utterance_plan
  --phase realize     只生成 V2 的 realized_messages
  --phase gold        只生成 V2 的 gold 期望结果
  --phase validate    只生成 V2 的 checks 校验结果
  --phase compile     生成完整 V2 输入对象 + execution_plan
  --phase execute     只执行 execution_plan.json
  --phase collect     只拉取 lark_fetch_records.jsonl
  --phase adapt       只生成 ingress / report 产物
  --phase full        依次执行 compile + execute + collect + adapt（默认）

参数说明：
  --case-spec <path>      case spec JSON 文件路径
  --dataset-root <path>   数据集输出根目录，默认：amem_docs/ds/feishu_im_dataset_v2
  --case-dir <path>       已存在的 case 目录；如果能从 case-spec 推导出来，可以不传
  --dry-run               在 execute/full 阶段使用 dry-run
  --skip-auth             跳过 lark-cli 登录态预检查
  --resume                复用已有产物，不先清理旧文件
  -h, --help              显示帮助

示例：
  amem_docs/scripts/feishu-builder-agent-run.sh
  amem_docs/scripts/feishu-builder-agent-run.sh --phase case-world
  amem_docs/scripts/feishu-builder-agent-run.sh --phase plan
  amem_docs/scripts/feishu-builder-agent-run.sh --phase compile
  amem_docs/scripts/feishu-builder-agent-run.sh --phase execute --case-dir amem_docs/ds/feishu_im_dataset_v2/cases/case_feishu_231_example
  amem_docs/scripts/feishu-builder-agent-run.sh --phase full --dry-run --skip-auth
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --phase)
      PHASE="${2:?missing value for --phase}"
      shift 2
      ;;
    --case-spec)
      CASE_SPEC="${2:?missing value for --case-spec}"
      shift 2
      ;;
    --dataset-root)
      DATASET_ROOT="${2:?missing value for --dataset-root}"
      shift 2
      ;;
    --case-dir)
      CASE_DIR="${2:?missing value for --case-dir}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --skip-auth)
      SKIP_AUTH=1
      shift
      ;;
    --resume)
      FRESH_RUN=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数：$1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "缺少必要命令：$1" >&2
    exit 1
  fi
}

require_cmd python3

case "${PHASE}" in
  case-world|plan|utterance|realize|gold|validate|compile|execute|collect|adapt|full)
    ;;
  *)
    echo "不支持的阶段：${PHASE}" >&2
    usage >&2
    exit 1
    ;;
esac

if [[ -f "${CASE_SPEC}" && -z "${CASE_DIR}" ]]; then
  CASE_DIR="$(
    python3 - <<'PY' "${CASE_SPEC}" "${DATASET_ROOT}"
from __future__ import annotations
import json
import sys
from pathlib import Path
case_spec = Path(sys.argv[1])
dataset_root = Path(sys.argv[2])
payload = json.loads(case_spec.read_text(encoding="utf-8"))
case_id = str(payload.get("case_id") or "").strip()
print(dataset_root / "cases" / case_id if case_id else "")
PY
  )"
fi

if [[ "${PHASE}" == "case-world" || "${PHASE}" == "plan" || "${PHASE}" == "utterance" || "${PHASE}" == "realize" || "${PHASE}" == "gold" || "${PHASE}" == "validate" || "${PHASE}" == "compile" || "${PHASE}" == "full" ]]; then
  if [[ ! -f "${CASE_SPEC}" ]]; then
    echo "未找到 case spec：${CASE_SPEC}" >&2
    exit 1
  fi
fi

if [[ "${PHASE}" == "execute" || "${PHASE}" == "collect" || "${PHASE}" == "adapt" ]]; then
  if [[ -z "${CASE_DIR}" || ! -d "${CASE_DIR}" ]]; then
    echo "未找到 case 目录：${CASE_DIR}" >&2
    exit 1
  fi
fi

if [[ "${PHASE}" == "execute" || "${PHASE}" == "collect" || "${PHASE}" == "full" ]]; then
  require_cmd lark-cli
  if [[ "${SKIP_AUTH}" -ne 1 ]]; then
    echo "[预检查] 正在检查 lark-cli 登录状态..."
    lark-cli auth status >/dev/null
  fi
fi

mkdir -p "${DATASET_ROOT}"
RUN_LOG_DIR="${DATASET_ROOT}/_runs"
mkdir -p "${RUN_LOG_DIR}"

clean_case_outputs() {
  local case_spec_path="$1"
  local dataset_root_path="$2"
  python3 - <<'PY' "${case_spec_path}" "${dataset_root_path}"
from __future__ import annotations

import json
import sys
from pathlib import Path

case_spec_path = Path(sys.argv[1])
dataset_root = Path(sys.argv[2])
payload = json.loads(case_spec_path.read_text(encoding="utf-8"))
case_id = str(payload.get("case_id") or "").strip()
if not case_id:
    raise SystemExit(0)
case_dir = dataset_root / "cases" / case_id
for relative in [
    "input/case_seed.json",
    "input/case_world.json",
    "story.json",
    "characters.json",
    "conflict_timeline.json",
    "input/characters.json",
    "input/conversation_plan.json",
    "input/utterance_plan.jsonl",
    "data/realized_messages.jsonl",
    "gold/expected_events.jsonl",
    "gold/expected_memory_blocks.json",
    "gold/expected_current_state.json",
    "checks/conversation_complexity_report.json",
    "checks/dataset_validation_report.json",
    "execution_result.json",
    "lark_fetch_records.jsonl",
    "openclaw_message_ingress.jsonl",
    "adapter_report.json",
    "build_report.json",
]:
    target = case_dir / relative
    if target.exists():
        target.unlink()
PY
}

run_python_json() {
  local log_name="$1"
  shift
  local run_log="${RUN_LOG_DIR}/${log_name}"
  echo "[执行] $*"
  "$@" | tee "${run_log}"
}

print_case_summary() {
  local path="$1"
  python3 - <<'PY' "${path}"
from __future__ import annotations

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
payload = json.loads(path.read_text(encoding="utf-8"))
if "case_dir" in payload:
    print(f"[完成] case_dir={payload.get('case_dir')}")
    print(f"[完成] llm_mode={payload.get('llm_mode')}")
elif payload.get("compiled"):
    compiled = payload.get("compiled") or {}
    execution_result = payload.get("execution_result") or {}
    adapted = payload.get("adapted") or {}
    report = adapted.get("build_report") or {}
    print(f"[完成] case_dir={compiled.get('case_dir')}")
    print(f"[完成] llm_mode={compiled.get('llm_mode')}")
    print(f"[完成] execution_status={execution_result.get('status')}")
    if report:
        print(f"[完成] ingress_events={report.get('num_openclaw_ingress_events')}")
        print(f"[完成] lark_messages={report.get('num_lark_messages_collected')}")
else:
    print(json.dumps(payload, ensure_ascii=False, indent=2))
PY
}

collect_only() {
  local case_dir_path="$1"
  python3 - <<'PY' "${case_dir_path}"
from __future__ import annotations

from pathlib import Path
from feishu_builder_agent.collector import collect_fetch_records
from feishu_builder_agent.io_utils import read_json, write_jsonl

case_dir = Path(__import__("sys").argv[1])
plan = read_json(case_dir / "execution_plan.json")
result = read_json(case_dir / "execution_result.json")
rows = collect_fetch_records(plan, result)
write_jsonl(case_dir / "lark_fetch_records.jsonl", rows)
print({
    "case_dir": str(case_dir),
    "fetch_records": len(rows),
    "output": str(case_dir / "lark_fetch_records.jsonl"),
})
PY
}

adapt_only() {
  local case_dir_path="$1"
  python3 - <<'PY' "${case_dir_path}"
from __future__ import annotations

from pathlib import Path
from feishu_builder_agent.cli import adapt_case
import json

case_dir = Path(__import__("sys").argv[1])
result = adapt_case(case_dir_path=case_dir)
print(json.dumps(result, ensure_ascii=False, indent=2))
PY
}

if [[ "${FRESH_RUN}" -eq 1 && ( "${PHASE}" == "case-world" || "${PHASE}" == "plan" || "${PHASE}" == "utterance" || "${PHASE}" == "realize" || "${PHASE}" == "gold" || "${PHASE}" == "validate" || "${PHASE}" == "compile" || "${PHASE}" == "full" ) ]]; then
  clean_case_outputs "${CASE_SPEC}" "${DATASET_ROOT}"
fi

case "${PHASE}" in
  case-world)
    RUN_LOG="${RUN_LOG_DIR}/generate-case-world.json"
    run_python_json "generate-case-world.json" python3 -m feishu_builder_agent.cli generate-case-world --case-spec "${CASE_SPEC}" --dataset-root "${DATASET_ROOT}"
    ;;
  plan)
    RUN_LOG="${RUN_LOG_DIR}/generate-conversation-plan.json"
    run_python_json "generate-conversation-plan.json" python3 -m feishu_builder_agent.cli generate-conversation-plan --case-spec "${CASE_SPEC}" --dataset-root "${DATASET_ROOT}"
    ;;
  utterance)
    RUN_LOG="${RUN_LOG_DIR}/generate-utterances.json"
    run_python_json "generate-utterances.json" python3 -m feishu_builder_agent.cli generate-utterances --case-spec "${CASE_SPEC}" --dataset-root "${DATASET_ROOT}"
    ;;
  realize)
    RUN_LOG="${RUN_LOG_DIR}/realize-messages.json"
    run_python_json "realize-messages.json" python3 -m feishu_builder_agent.cli realize-messages --case-spec "${CASE_SPEC}" --dataset-root "${DATASET_ROOT}"
    ;;
  gold)
    RUN_LOG="${RUN_LOG_DIR}/generate-gold.json"
    run_python_json "generate-gold.json" python3 -m feishu_builder_agent.cli generate-gold --case-spec "${CASE_SPEC}" --dataset-root "${DATASET_ROOT}"
    ;;
  validate)
    RUN_LOG="${RUN_LOG_DIR}/validate-case.json"
    run_python_json "validate-case.json" python3 -m feishu_builder_agent.cli validate-case --case-spec "${CASE_SPEC}" --dataset-root "${DATASET_ROOT}"
    ;;
  compile)
    RUN_LOG="${RUN_LOG_DIR}/compile-case.json"
    run_python_json "compile-case.json" python3 -m feishu_builder_agent.cli compile-case --case-spec "${CASE_SPEC}" --dataset-root "${DATASET_ROOT}"
    print_case_summary "${RUN_LOG}"
    ;;
  execute)
    RUN_LOG="${RUN_LOG_DIR}/execute-case.json"
    ARGS=(python3 -m feishu_builder_agent.cli execute-case --case-dir "${CASE_DIR}")
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      ARGS+=(--dry-run)
    fi
    run_python_json "execute-case.json" "${ARGS[@]}"
    print_case_summary "${RUN_LOG}"
    ;;
  collect)
    RUN_LOG="${RUN_LOG_DIR}/collect-case.json"
    echo "[执行] 正在从 ${CASE_DIR} 拉取 fetch records"
    collect_only "${CASE_DIR}" | tee "${RUN_LOG}"
    ;;
  adapt)
    RUN_LOG="${RUN_LOG_DIR}/adapt-case.json"
    echo "[执行] 正在从 ${CASE_DIR} 生成适配后的 ingress / report 产物"
    adapt_only "${CASE_DIR}" | tee "${RUN_LOG}"
    ;;
  full)
    RUN_LOG="${RUN_LOG_DIR}/build-case.json"
    ARGS=(python3 -m feishu_builder_agent.cli build-case --case-spec "${CASE_SPEC}" --dataset-root "${DATASET_ROOT}")
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      ARGS+=(--dry-run)
    fi
    run_python_json "build-case.json" "${ARGS[@]}"
    print_case_summary "${RUN_LOG}"
    ;;
esac
