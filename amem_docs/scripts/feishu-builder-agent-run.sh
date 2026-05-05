#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

DEFAULT_CASE_SPEC="feishu_builder_agent/templates/default_case_spec.json"
PHASE="full"
CASE_SPEC="${DEFAULT_CASE_SPEC}"
CASE_SPEC_EXPLICIT=0
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
  如果没有显式传入 --case-spec，脚本会基于默认示例自动生成一个新的动态 case spec，
  每次都会得到新的 case_id / task_id / seed，然后再运行完整的 feishu_builder_agent V2 主流程：
    case-world -> characters -> plan -> target-gold -> command-plan
    -> execute -> collect -> gold -> validate -> adapt

阶段说明：
  --phase case-world
      从 case_spec 生成 case_seed / case_world。
      适合先检查：这个案例的业务背景、冲突轴、复杂度方向是否合理。
      跑完建议查看：input/case_world.json

  --phase characters
      根据 case_world 生成角色画像。
      这一阶段会同时为每个角色生成稳定的 simulated_open_id，可把它理解成这套 benchmark 的模拟工号。
      适合先检查：角色职责、立场、风险偏好、信息差是否像真实协作场景，以及模拟工号映射是否稳定。
      跑完建议查看：input/characters.json

  --phase plan
      生成 conversation_plan。
      适合先检查：session / topic / turns / 状态演化是否满足多轮要求。
      跑完建议查看：input/conversation_plan.json

  --phase target-gold
      先定义这个 case 期望形成哪些 topic、block、current state。
      适合先检查：评测目标是否清楚，而不是等执行完再事后总结。
      跑完建议查看：gold/target_state.json

  --phase command-plan
      生成真正要执行的 lark-cli 动作计划，并同步写出 execution_plan。
      适合先检查：每一步飞书动作、依赖关系、主群 / thread 的执行顺序是否正确。
      跑完建议查看：input/command_plan.jsonl、execution_plan.json

  --phase execute
      只执行 execution_plan.json，不做消息拉取和 gold 生成。
      适合先检查：lark-cli 是否能正常把动作发到真实飞书环境。
      跑完建议查看：execution_result.json

  --phase collect
      根据 execution_result 拉取真实飞书消息，并整理成 collected_messages。
      这一阶段会保留真实发送者 actual_sender，并按 characters.json 的 simulated_open_id 抬升成模拟角色身份。
      适合先检查：真实线上消息是否已经被成功收集回 dataset，以及角色映射是否按预期生效。
      跑完建议查看：lark_fetch_records.jsonl、data/collected_messages.jsonl

  --phase gold
      基于 target_state + collected_messages 生成 evidence-bound gold。
      适合先检查：gold 是否真的绑定到了真实消息证据，而不是只镜像计划。
      跑完建议查看：gold/expected_events.jsonl、gold/expected_current_state.json

  --phase validate
      做跨阶段一致性审计，不会重跑上游生成。
      适合最终检查：计划是否覆盖、执行是否完整、collect/gold 是否可追溯、复杂度是否达标。
      跑完建议查看：checks/conversation_complexity_report.json、checks/dataset_validation_report.json

  --phase adapt
      生成 ingress / report / replay 相关产物。
      这一阶段会把模拟身份写进标准 Feishu sender 字段，让 openclaw-lark 直接消费角色映射后的 open_id。
      适合接 OpenClaw 主链之前做最后转换。
      跑完建议查看：openclaw_message_ingress.jsonl、build_report.json

  --phase full
      从 case_spec 开始跑完整链路。
      适合真正做一遍 end-to-end 演练。

参数说明：
  --case-spec <path>      case spec JSON 文件路径
                         如果显式传入，脚本会按这个固定 spec 运行，不再自动生成动态 case。
  --dataset-root <path>   数据集输出根目录，默认：amem_docs/ds/feishu_im_dataset_v2
  --case-dir <path>       已存在的 case 目录；如果能从 case-spec 推导出来，可以不传
  --dry-run               在 execute/full 阶段使用 dry-run
  --skip-auth             跳过 lark-cli 登录态预检查
  --resume                复用已有产物，不先清理旧文件
  -h, --help              显示帮助

示例：
  1. 不传 case-spec，自动生成一个新的动态案例，然后只先确认 case 世界观和复杂度方向是否合理：
     amem_docs/scripts/feishu-builder-agent-run.sh --phase case-world

  2. 已经有 case_world 了，只想继续补角色画像：
     amem_docs/scripts/feishu-builder-agent-run.sh --phase characters
     这一步也会刷新每个角色的 simulated_open_id（模拟工号）映射。
     如果你前一步刚用动态 case 跑过 case-world，这里会默认接上最近一次生成的 case 目录。

  3. 想固定使用你自己写好的 spec，而不是自动生成动态 case：
     amem_docs/scripts/feishu-builder-agent-run.sh --phase full --case-spec path/to/your_case_spec.json

  4. 已经有对话计划了，只想重新生成可执行的 lark-cli 动作计划：
     amem_docs/scripts/feishu-builder-agent-run.sh --phase command-plan
     如果当前目录下有多个 case，也可以显式传 --case-dir 指向某一个固定 case。

  5. 已经执行过飞书动作，只想重新 collect 真实消息并重建 gold：
     amem_docs/scripts/feishu-builder-agent-run.sh --phase collect
     amem_docs/scripts/feishu-builder-agent-run.sh --phase gold

  6. 只做最终一致性审计，不重跑任何上游生成：
     amem_docs/scripts/feishu-builder-agent-run.sh --phase validate

  7. 从头到尾跑一遍完整链路，并自动生成新的动态 case：
     amem_docs/scripts/feishu-builder-agent-run.sh --phase full

  8. 只做 dry-run，不真的发飞书消息：
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
      CASE_SPEC_EXPLICIT=1
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

prepare_dynamic_case_spec() {
  local base_case_spec="$1"
  local dataset_root_path="$2"
  python3 - <<'PY' "${base_case_spec}" "${dataset_root_path}"
from __future__ import annotations

import json
import random
import re
import sys
from datetime import datetime
from pathlib import Path

base_case_spec = Path(sys.argv[1])
dataset_root = Path(sys.argv[2])
payload = json.loads(base_case_spec.read_text(encoding="utf-8"))
now = datetime.now()
stamp = now.strftime("%Y%m%d%H%M%S")
suffix = f"{random.randint(100, 999)}"
task_id = f"FEISHU-{stamp}{suffix}"
case_id = f"case_feishu_{stamp}{suffix}_example"

payload["task_id"] = task_id
payload["case_id"] = case_id
payload["seed"] = int(f"{stamp[-6:]}{suffix}")
payload["main_goal"] = re.sub(r"FEISHU-\d+", task_id, str(payload.get("main_goal") or ""))

spec_dir = dataset_root / "_generated_case_specs"
spec_dir.mkdir(parents=True, exist_ok=True)
output_path = spec_dir / f"{case_id}.json"
output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(output_path)
PY
}

derive_case_dir_from_case_spec() {
  local case_spec_path="$1"
  local dataset_root_path="$2"
  python3 - <<'PY' "${case_spec_path}" "${dataset_root_path}"
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
}

case "${PHASE}" in
  case-world|characters|plan|target-gold|command-plan|gold|validate|execute|collect|adapt|full)
    ;;
  *)
    echo "不支持的阶段：${PHASE}" >&2
    usage >&2
    exit 1
    ;;
esac

if [[ "${PHASE}" == "case-world" || "${PHASE}" == "full" ]]; then
  if [[ "${CASE_SPEC_EXPLICIT}" -ne 1 && "${CASE_SPEC}" == "${DEFAULT_CASE_SPEC}" ]]; then
    CASE_SPEC="$(prepare_dynamic_case_spec "${DEFAULT_CASE_SPEC}" "${DATASET_ROOT}")"
    echo "[动态 case] 已基于默认示例生成新的 case spec：${CASE_SPEC}"
  fi
  if [[ ! -f "${CASE_SPEC}" ]]; then
    echo "未找到 case spec：${CASE_SPEC}" >&2
    exit 1
  fi
fi

mkdir -p "${DATASET_ROOT}"
RUN_LOG_DIR="${DATASET_ROOT}/_runs"
mkdir -p "${RUN_LOG_DIR}"
LAST_CASE_DIR_FILE="${RUN_LOG_DIR}/last_case_dir.txt"
LAST_CASE_SPEC_FILE="${RUN_LOG_DIR}/last_case_spec.txt"

load_latest_case_dir() {
  if [[ -f "${LAST_CASE_DIR_FILE}" ]]; then
    cat "${LAST_CASE_DIR_FILE}"
  fi
}

persist_latest_case_refs() {
  local case_dir_path="$1"
  local case_spec_path="$2"
  printf '%s\n' "${case_dir_path}" > "${LAST_CASE_DIR_FILE}"
  if [[ -n "${case_spec_path}" ]]; then
    printf '%s\n' "${case_spec_path}" > "${LAST_CASE_SPEC_FILE}"
  fi
}

if [[ -z "${CASE_DIR}" && -f "${CASE_SPEC}" && ( "${CASE_SPEC_EXPLICIT}" -eq 1 || "${PHASE}" == "case-world" || "${PHASE}" == "full" ) ]]; then
  CASE_DIR="$(derive_case_dir_from_case_spec "${CASE_SPEC}" "${DATASET_ROOT}")"
fi

if [[ "${PHASE}" == "characters" || "${PHASE}" == "plan" || "${PHASE}" == "target-gold" || "${PHASE}" == "command-plan" || "${PHASE}" == "gold" || "${PHASE}" == "validate" || "${PHASE}" == "execute" || "${PHASE}" == "collect" || "${PHASE}" == "adapt" ]]; then
  if [[ -z "${CASE_DIR}" ]]; then
    CASE_DIR="$(load_latest_case_dir)"
  fi
fi

if [[ "${PHASE}" == "characters" || "${PHASE}" == "plan" || "${PHASE}" == "target-gold" || "${PHASE}" == "command-plan" || "${PHASE}" == "gold" || "${PHASE}" == "validate" || "${PHASE}" == "execute" || "${PHASE}" == "collect" || "${PHASE}" == "adapt" ]]; then
  if [[ -z "${CASE_DIR}" || ! -d "${CASE_DIR}" ]]; then
    echo "未找到 case 目录：${CASE_DIR}" >&2
    echo "如果你刚跑过动态 case，请先运行 --phase case-world，或显式传入 --case-dir。" >&2
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
    "gold/target_state.json",
    "input/command_plan.jsonl",
    "data/collected_messages.jsonl",
    "gold/expected_events.jsonl",
    "gold/expected_memory_blocks.json",
    "gold/expected_current_state.json",
    "checks/conversation_complexity_report.json",
    "checks/dataset_validation_report.json",
    "execution_plan.json",
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
  local stderr_log="${run_log%.json}.stderr.log"
  local stderr_pipe
  local tee_pid
  echo "[执行] $*"
  stderr_pipe="$(mktemp -u "${TMPDIR:-/tmp}/feishu-builder-stderr.XXXXXX")"
  mkfifo "${stderr_pipe}"
  tee "${stderr_log}" < "${stderr_pipe}" >&2 &
  tee_pid=$!
  "$@" 2> "${stderr_pipe}" | tee "${run_log}"
  local cmd_status=${PIPESTATUS[0]}
  wait "${tee_pid}" || true
  rm -f "${stderr_pipe}"
  return "${cmd_status}"
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

if [[ "${FRESH_RUN}" -eq 1 && ( "${PHASE}" == "case-world" || "${PHASE}" == "full" ) ]]; then
  clean_case_outputs "${CASE_SPEC}" "${DATASET_ROOT}"
fi

if [[ -n "${CASE_SPEC}" && ( "${PHASE}" == "case-world" || "${PHASE}" == "full" ) ]]; then
  echo "[目标 spec] case_spec=${CASE_SPEC}"
fi
if [[ -n "${CASE_DIR}" ]]; then
  echo "[目标 case] case_dir=${CASE_DIR}"
fi

case "${PHASE}" in
  case-world)
    RUN_LOG="${RUN_LOG_DIR}/generate-case-world.json"
    run_python_json "generate-case-world.json" python3 -m feishu_builder_agent.cli generate-case-world --case-spec "${CASE_SPEC}" --dataset-root "${DATASET_ROOT}"
    persist_latest_case_refs "${CASE_DIR}" "${CASE_SPEC}"
    ;;
  characters)
    RUN_LOG="${RUN_LOG_DIR}/generate-characters.json"
    run_python_json "generate-characters.json" python3 -m feishu_builder_agent.cli generate-characters --case-dir "${CASE_DIR}"
    persist_latest_case_refs "${CASE_DIR}" ""
    ;;
  plan)
    RUN_LOG="${RUN_LOG_DIR}/generate-conversation-plan.json"
    run_python_json "generate-conversation-plan.json" python3 -m feishu_builder_agent.cli generate-conversation-plan --case-dir "${CASE_DIR}"
    persist_latest_case_refs "${CASE_DIR}" ""
    ;;
  target-gold)
    RUN_LOG="${RUN_LOG_DIR}/generate-target-gold.json"
    run_python_json "generate-target-gold.json" python3 -m feishu_builder_agent.cli generate-target-gold --case-dir "${CASE_DIR}"
    persist_latest_case_refs "${CASE_DIR}" ""
    ;;
  command-plan)
    RUN_LOG="${RUN_LOG_DIR}/generate-command-plan.json"
    run_python_json "generate-command-plan.json" python3 -m feishu_builder_agent.cli generate-command-plan --case-dir "${CASE_DIR}"
    persist_latest_case_refs "${CASE_DIR}" ""
    ;;
  gold)
    RUN_LOG="${RUN_LOG_DIR}/generate-gold.json"
    run_python_json "generate-gold.json" python3 -m feishu_builder_agent.cli generate-gold --case-dir "${CASE_DIR}"
    persist_latest_case_refs "${CASE_DIR}" ""
    ;;
  validate)
    RUN_LOG="${RUN_LOG_DIR}/validate-case.json"
    run_python_json "validate-case.json" python3 -m feishu_builder_agent.cli validate-case --case-dir "${CASE_DIR}"
    persist_latest_case_refs "${CASE_DIR}" ""
    ;;
  execute)
    RUN_LOG="${RUN_LOG_DIR}/execute-case.json"
    ARGS=(python3 -m feishu_builder_agent.cli execute-case --case-dir "${CASE_DIR}")
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      ARGS+=(--dry-run)
    fi
    run_python_json "execute-case.json" "${ARGS[@]}"
    persist_latest_case_refs "${CASE_DIR}" ""
    print_case_summary "${RUN_LOG}"
    ;;
  collect)
    RUN_LOG="${RUN_LOG_DIR}/collect-case.json"
    run_python_json "collect-case.json" python3 -m feishu_builder_agent.cli collect-case --case-dir "${CASE_DIR}"
    persist_latest_case_refs "${CASE_DIR}" ""
    ;;
  adapt)
    RUN_LOG="${RUN_LOG_DIR}/adapt-case.json"
    run_python_json "adapt-case.json" python3 -m feishu_builder_agent.cli adapt-case --case-dir "${CASE_DIR}"
    persist_latest_case_refs "${CASE_DIR}" ""
    ;;
  full)
    RUN_LOG="${RUN_LOG_DIR}/build-case.json"
    ARGS=(python3 -m feishu_builder_agent.cli build-case --case-spec "${CASE_SPEC}" --dataset-root "${DATASET_ROOT}")
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      ARGS+=(--dry-run)
    fi
    run_python_json "build-case.json" "${ARGS[@]}"
    persist_latest_case_refs "${CASE_DIR}" "${CASE_SPEC}"
    print_case_summary "${RUN_LOG}"
    ;;
esac
