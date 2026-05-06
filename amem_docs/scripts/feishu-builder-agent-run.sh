#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

PHASE="full"
CASE_SPEC=""
CASE_SPEC_EXPLICIT=0
DATASET_ROOT="amem_docs/ds/feishu_im_dataset_v3"
CASE_DIR=""
DRY_RUN=0
SKIP_AUTH=0
FRESH_RUN=1
DIFFICULTY="$(python3 - <<'PY'
from feishu_builder_agent.builder_settings import resolve_default_difficulty
print(resolve_default_difficulty())
PY
)"
SEED=""
COMPARISON_TARGET=""
PRIMARY_FAILURE_MODE=""
SELECTED_FAILURE_MODES=()
REQUIRE_LIVE_LLM=0

usage() {
  cat <<'EOF'
用法：
  amem_docs/scripts/feishu-builder-agent-run.sh [options]

默认行为：
  如果没有显式传入 --case-spec，脚本会先运行 V3 `spec-generation` 生成新的 case_spec，
  然后按 V3 正式链路执行三阶段：
    compile-case-phase1 -> compile-case-phase2 -> compile-case-phase3

阶段说明：
  --phase spec-generation
      生成最小 V3 case_spec。
      跑完建议查看：case_spec.json

  --phase memory-failure-blueprint
      基于 case_spec 生成正式的 `memory_failure_blueprint.json`。

  --phase task-actor-layout
      生成 target task / distractor tasks / shared actor slots。

  --phase case-world
      生成自然企业协作背景。

  --phase characters
      生成 `characters.json` 与 `actor_registry.json`。

  --phase state-trajectory
      生成 current-state / stale-state / supersession 轨迹。

  --phase conversation-plan
      生成多 source、多 session 的对话计划。

  --phase command-plan
      生成可执行动作计划 `command_plan.jsonl`。

  --phase execute
      执行动作计划。

  --phase collect
      收集真实消息，生成 `collected_messages.jsonl` 与 `openclaw_message_ingress.jsonl`。

  --phase pre-annotation-validate
      审计 trap 是否已经落地。

  --phase annotation-gold
      基于最终 observed data 生成 annotation-only gold。

  --phase build-checks
      生成 `complexity_gate / integrity_gate / eval_manifest`。

  --phase gold-validate
      检查 gold 与 observed data 一致性。

  --phase replay-runtime
      调真实 Task Wiki runtime 生成 predictions。

  --phase replay-eval
      生成 event / block / QA 分层评测。

  --phase memory-md-baseline
      运行 OpenClaw Memory.md baseline。

  --phase value-eval
      生成 baseline comparison。

  --phase report
      汇总最终报告。

  --phase full
      顺序执行：
        compile-case-phase1
        -> compile-case-phase2
        -> compile-case-phase3

  --phase compile-case-phase1
      直接执行 V3 Phase 1。

  --phase compile-case-phase2
      直接执行 V3 Phase 2。

  --phase compile-case-phase3
      直接执行 V3 Phase 3。

参数说明：
  --case-spec <path>            V3 case spec JSON 文件路径
  --dataset-root <path>         数据集输出根目录，默认：amem_docs/ds/feishu_im_dataset_v3
  --case-dir <path>             已存在的 case 目录；如果能从 case-spec 推导出来，可以不传
  --difficulty <level>          spec-generation 复杂度；默认读取 builder_settings.yml
  --seed <int>                  可选固定随机种子
  --comparison-target <id>      可选 comparison target
  --selected-failure-mode <id>  可重复传入，指定 selected_failure_modes
  --primary-failure-mode <id>   可选 primary_failure_mode
  --require-live-llm            要求所有可生成阶段必须使用 live LLM；否则直接失败
  --dry-run                     在 execute/collect/full 阶段使用 dry-run
  --skip-auth                   跳过 lark-cli 登录态预检查
  --resume                      复用已有产物，不先清理旧文件
  -h, --help                    显示帮助

示例：
  1. 从头生成一个新的 V3 case_spec：
     amem_docs/scripts/feishu-builder-agent-run.sh --phase spec-generation

  2. 跑完整 V3 三阶段，但不真实发飞书消息：
     amem_docs/scripts/feishu-builder-agent-run.sh --phase full --dry-run --skip-auth

  3. 对已有 case 只做 Phase 2：
     amem_docs/scripts/feishu-builder-agent-run.sh --phase compile-case-phase2 --case-dir path/to/case
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
    --difficulty)
      DIFFICULTY="${2:?missing value for --difficulty}"
      shift 2
      ;;
    --seed)
      SEED="${2:?missing value for --seed}"
      shift 2
      ;;
    --comparison-target)
      COMPARISON_TARGET="${2:?missing value for --comparison-target}"
      shift 2
      ;;
    --selected-failure-mode)
      SELECTED_FAILURE_MODES+=("${2:?missing value for --selected-failure-mode}")
      shift 2
      ;;
    --primary-failure-mode)
      PRIMARY_FAILURE_MODE="${2:?missing value for --primary-failure-mode}"
      shift 2
      ;;
    --case-dir)
      CASE_DIR="${2:?missing value for --case-dir}"
      shift 2
      ;;
    --require-live-llm)
      REQUIRE_LIVE_LLM=1
      shift
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

if [[ "${REQUIRE_LIVE_LLM}" -eq 1 ]]; then
  export FEISHU_BUILDER_REQUIRE_LIVE_LLM=1
fi

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

json_get() {
  local json_path="$1"
  local expression="$2"
  python3 - <<'PY' "${json_path}" "${expression}"
from __future__ import annotations
import json
import sys

payload = json.loads(open(sys.argv[1], encoding="utf-8").read())
parts = [part for part in sys.argv[2].split(".") if part]
value = payload
for part in parts:
    value = value[part]
print(value)
PY
}

validate_json_file() {
  local json_path="$1"
  local command_desc="$2"
  local stderr_log="$3"
  python3 - <<'PY' "${json_path}" "${command_desc}" "${stderr_log}"
from __future__ import annotations
import json
import sys
from pathlib import Path

json_path = Path(sys.argv[1])
command_desc = sys.argv[2]
stderr_log = sys.argv[3]
text = json_path.read_text(encoding="utf-8").strip()
if not text:
    raise SystemExit(f"[错误] CLI 没有返回 JSON 输出: {command_desc}\n[定位] stdout log={json_path}\n[定位] stderr log={stderr_log}")
try:
    json.loads(text)
except json.JSONDecodeError as exc:
    raise SystemExit(
        f"[错误] CLI 返回的 stdout 不是合法 JSON: {command_desc}\n"
        f"[定位] stdout log={json_path}\n[定位] stderr log={stderr_log}\n"
        f"[原因] {exc}"
    )
PY
}

PHASES_WITH_CASE_SPEC=(
  "case-world"
  "full"
  "compile-case-phase1"
)
PHASES_WITH_CASE_DIR=(
  "memory-failure-blueprint"
  "task-actor-layout"
  "characters"
  "state-trajectory"
  "conversation-plan"
  "command-plan"
  "execute"
  "collect"
  "pre-annotation-validate"
  "annotation-gold"
  "build-checks"
  "gold-validate"
  "replay-runtime"
  "replay-eval"
  "memory-md-baseline"
  "value-eval"
  "report"
  "compile-case-phase2"
  "compile-case-phase3"
)

contains_phase() {
  local needle="$1"
  shift
  local item
  for item in "$@"; do
    if [[ "${item}" == "${needle}" ]]; then
      return 0
    fi
  done
  return 1
}

VALID_PHASES=(
  "spec-generation"
  "memory-failure-blueprint"
  "task-actor-layout"
  "case-world"
  "characters"
  "state-trajectory"
  "conversation-plan"
  "command-plan"
  "execute"
  "collect"
  "pre-annotation-validate"
  "annotation-gold"
  "build-checks"
  "gold-validate"
  "replay-runtime"
  "replay-eval"
  "memory-md-baseline"
  "value-eval"
  "report"
  "compile-case-phase1"
  "compile-case-phase2"
  "compile-case-phase3"
  "full"
)

if ! contains_phase "${PHASE}" "${VALID_PHASES[@]}"; then
  echo "不支持的阶段：${PHASE}" >&2
  usage >&2
  exit 1
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

load_latest_case_spec() {
  if [[ -f "${LAST_CASE_SPEC_FILE}" ]]; then
    cat "${LAST_CASE_SPEC_FILE}"
  fi
}

persist_latest_case_refs() {
  local case_dir_path="$1"
  local case_spec_path="$2"
  if [[ -n "${case_dir_path}" ]]; then
    printf '%s\n' "${case_dir_path}" > "${LAST_CASE_DIR_FILE}"
  fi
  if [[ -n "${case_spec_path}" ]]; then
    printf '%s\n' "${case_spec_path}" > "${LAST_CASE_SPEC_FILE}"
  fi
}

if [[ -z "${CASE_SPEC}" && "${CASE_SPEC_EXPLICIT}" -ne 1 ]] && contains_phase "${PHASE}" "${PHASES_WITH_CASE_SPEC[@]}"; then
  CASE_SPEC="$(load_latest_case_spec)"
fi

if [[ -z "${CASE_DIR}" && -n "${CASE_SPEC}" && -f "${CASE_SPEC}" ]]; then
  CASE_DIR="$(derive_case_dir_from_case_spec "${CASE_SPEC}" "${DATASET_ROOT}")"
fi

if [[ -z "${CASE_DIR}" ]] && contains_phase "${PHASE}" "${PHASES_WITH_CASE_DIR[@]}"; then
  CASE_DIR="$(load_latest_case_dir)"
fi

if contains_phase "${PHASE}" "${PHASES_WITH_CASE_DIR[@]}"; then
  if [[ -z "${CASE_DIR}" || ! -d "${CASE_DIR}" ]]; then
    echo "未找到 case 目录：${CASE_DIR}" >&2
    echo "请先运行 spec-generation / case-world / full，或显式传入 --case-dir。" >&2
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
  if [[ -z "${case_spec_path}" || ! -f "${case_spec_path}" ]]; then
    return 0
  fi
  python3 - <<'PY' "${case_spec_path}" "${dataset_root_path}"
from __future__ import annotations

import json
import shutil
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
    "input/memory_failure_blueprint.json",
    "input/task_actor_layout.json",
    "input/case_world.json",
    "input/characters.json",
    "input/actor_registry.json",
    "input/state_trajectory.json",
    "input/conversation_plan.json",
    "input/command_plan.jsonl",
    "data/collected_messages.jsonl",
    "data/openclaw_message_ingress.jsonl",
    "checks/pre_annotation_validation_report.json",
    "checks/complexity_gate.json",
    "checks/integrity_gate.json",
    "checks/eval_manifest.json",
    "case_manifest.json",
]:
    target = case_dir / relative
    if target.exists():
        target.unlink()
for relative in ["gold", "predictions", "reports"]:
    target = case_dir / relative
    if target.exists():
        shutil.rmtree(target)
PY
}

run_python_json() {
  local log_name="$1"
  shift
  local run_log="${RUN_LOG_DIR}/${log_name}"
  local stderr_log="${run_log%.json}.stderr.log"
  local stderr_pipe
  local tee_pid
  local cmd_status
  local command_desc="$*"
  echo "[执行] ${command_desc}"
  stderr_pipe="$(mktemp -u "${TMPDIR:-/tmp}/feishu-builder-stderr.XXXXXX")"
  mkfifo "${stderr_pipe}"
  tee "${stderr_log}" < "${stderr_pipe}" >&2 &
  tee_pid=$!
  "$@" 2> "${stderr_pipe}" | tee "${run_log}"
  cmd_status=${PIPESTATUS[0]}
  wait "${tee_pid}" || true
  rm -f "${stderr_pipe}"
  if [[ "${cmd_status}" -ne 0 ]]; then
    echo "[错误] 命令执行失败：${command_desc}" >&2
    echo "[定位] stdout log=${run_log}" >&2
    echo "[定位] stderr log=${stderr_log}" >&2
    return "${cmd_status}"
  fi
  validate_json_file "${run_log}" "${command_desc}" "${stderr_log}"
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
case_dir = payload.get("case_dir")
if case_dir:
    print(f"[完成] case_dir={case_dir}")
if "llm_mode" in payload:
    print(f"[完成] llm_mode={payload.get('llm_mode')}")
if "llm_generation_modes" in payload:
    print(f"[完成] llm_generation_modes={payload.get('llm_generation_modes')}")
if "pre_annotation_validation_report" in payload:
    report = payload["pre_annotation_validation_report"]
    print(f"[完成] trap_validation_passed={report.get('overall_status')}")
if "reports" in payload:
    print("[完成] replay_eval=ready")
if "value_eval" in payload:
    print("[完成] value_eval=ready")
if "report" in payload:
    print("[完成] final_report=ready")
PY
}

run_spec_generation_if_needed() {
  if [[ -n "${CASE_SPEC}" && -f "${CASE_SPEC}" ]]; then
    return 0
  fi
  local args=(python3 -m feishu_builder_agent.cli spec-generation --dataset-root "${DATASET_ROOT}" --difficulty "${DIFFICULTY}")
  if [[ -n "${SEED}" ]]; then
    args+=(--seed "${SEED}")
  fi
  if [[ -n "${COMPARISON_TARGET}" ]]; then
    args+=(--comparison-target "${COMPARISON_TARGET}")
  fi
  local mode
  if [[ "${#SELECTED_FAILURE_MODES[@]}" -gt 0 ]]; then
    for mode in "${SELECTED_FAILURE_MODES[@]}"; do
      args+=(--selected-failure-mode "${mode}")
    done
  fi
  if [[ -n "${PRIMARY_FAILURE_MODE}" ]]; then
    args+=(--primary-failure-mode "${PRIMARY_FAILURE_MODE}")
  fi
  run_python_json "spec-generation.json" "${args[@]}"
  CASE_SPEC="$(json_get "${RUN_LOG_DIR}/spec-generation.json" "case_spec_path")"
  CASE_DIR="$(json_get "${RUN_LOG_DIR}/spec-generation.json" "case_dir")"
  persist_latest_case_refs "${CASE_DIR}" "${CASE_SPEC}"
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
  spec-generation)
    run_spec_generation_if_needed
    print_case_summary "${RUN_LOG_DIR}/spec-generation.json"
    ;;
  memory-failure-blueprint)
    run_python_json "memory-failure-blueprint.json" python3 -m feishu_builder_agent.cli memory-failure-blueprint --case-dir "${CASE_DIR}"
    persist_latest_case_refs "${CASE_DIR}" ""
    print_case_summary "${RUN_LOG_DIR}/memory-failure-blueprint.json"
    ;;
  task-actor-layout)
    run_python_json "task-actor-layout.json" python3 -m feishu_builder_agent.cli task-actor-layout --case-dir "${CASE_DIR}"
    persist_latest_case_refs "${CASE_DIR}" ""
    print_case_summary "${RUN_LOG_DIR}/task-actor-layout.json"
    ;;
  case-world)
    run_spec_generation_if_needed
    run_python_json "case-world.json" python3 -m feishu_builder_agent.cli case-world --case-spec-path "${CASE_SPEC}" --dataset-root "${DATASET_ROOT}"
    persist_latest_case_refs "${CASE_DIR}" "${CASE_SPEC}"
    print_case_summary "${RUN_LOG_DIR}/case-world.json"
    ;;
  characters)
    run_python_json "characters.json" python3 -m feishu_builder_agent.cli characters --case-dir "${CASE_DIR}"
    persist_latest_case_refs "${CASE_DIR}" ""
    print_case_summary "${RUN_LOG_DIR}/characters.json"
    ;;
  state-trajectory)
    run_python_json "state-trajectory.json" python3 -m feishu_builder_agent.cli state-trajectory --case-dir "${CASE_DIR}"
    persist_latest_case_refs "${CASE_DIR}" ""
    print_case_summary "${RUN_LOG_DIR}/state-trajectory.json"
    ;;
  conversation-plan)
    run_python_json "conversation-plan.json" python3 -m feishu_builder_agent.cli conversation-plan --case-dir "${CASE_DIR}"
    persist_latest_case_refs "${CASE_DIR}" ""
    print_case_summary "${RUN_LOG_DIR}/conversation-plan.json"
    ;;
  command-plan)
    run_python_json "command-plan.json" python3 -m feishu_builder_agent.cli command-plan --case-dir "${CASE_DIR}"
    persist_latest_case_refs "${CASE_DIR}" ""
    print_case_summary "${RUN_LOG_DIR}/command-plan.json"
    ;;
  execute)
    ARGS=(python3 -m feishu_builder_agent.cli execute --case-dir "${CASE_DIR}")
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      ARGS+=(--dry-run)
    fi
    run_python_json "execute.json" "${ARGS[@]}"
    persist_latest_case_refs "${CASE_DIR}" ""
    print_case_summary "${RUN_LOG_DIR}/execute.json"
    ;;
  collect)
    ARGS=(python3 -m feishu_builder_agent.cli collect --case-dir "${CASE_DIR}")
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      ARGS+=(--dry-run)
    fi
    run_python_json "collect.json" "${ARGS[@]}"
    persist_latest_case_refs "${CASE_DIR}" ""
    print_case_summary "${RUN_LOG_DIR}/collect.json"
    ;;
  pre-annotation-validate)
    run_python_json "pre-annotation-validate.json" python3 -m feishu_builder_agent.cli pre-annotation-validate --case-dir "${CASE_DIR}"
    persist_latest_case_refs "${CASE_DIR}" ""
    print_case_summary "${RUN_LOG_DIR}/pre-annotation-validate.json"
    ;;
  annotation-gold)
    run_python_json "annotation-gold.json" python3 -m feishu_builder_agent.cli annotation-gold --case-dir "${CASE_DIR}"
    persist_latest_case_refs "${CASE_DIR}" ""
    print_case_summary "${RUN_LOG_DIR}/annotation-gold.json"
    ;;
  build-checks)
    run_python_json "build-checks.json" python3 -m feishu_builder_agent.cli build-checks --case-dir "${CASE_DIR}"
    persist_latest_case_refs "${CASE_DIR}" ""
    print_case_summary "${RUN_LOG_DIR}/build-checks.json"
    ;;
  gold-validate)
    run_python_json "gold-validate.json" python3 -m feishu_builder_agent.cli gold-validate --case-dir "${CASE_DIR}"
    persist_latest_case_refs "${CASE_DIR}" ""
    print_case_summary "${RUN_LOG_DIR}/gold-validate.json"
    ;;
  replay-runtime)
    run_python_json "replay-runtime.json" python3 -m feishu_builder_agent.cli replay-runtime --case-dir "${CASE_DIR}"
    persist_latest_case_refs "${CASE_DIR}" ""
    print_case_summary "${RUN_LOG_DIR}/replay-runtime.json"
    ;;
  replay-eval)
    run_python_json "replay-eval.json" python3 -m feishu_builder_agent.cli replay-eval --case-dir "${CASE_DIR}"
    persist_latest_case_refs "${CASE_DIR}" ""
    print_case_summary "${RUN_LOG_DIR}/replay-eval.json"
    ;;
  memory-md-baseline)
    run_python_json "memory-md-baseline.json" python3 -m feishu_builder_agent.cli memory-md-baseline --case-dir "${CASE_DIR}"
    persist_latest_case_refs "${CASE_DIR}" ""
    print_case_summary "${RUN_LOG_DIR}/memory-md-baseline.json"
    ;;
  value-eval)
    run_python_json "value-eval.json" python3 -m feishu_builder_agent.cli value-eval --case-dir "${CASE_DIR}"
    persist_latest_case_refs "${CASE_DIR}" ""
    print_case_summary "${RUN_LOG_DIR}/value-eval.json"
    ;;
  report)
    run_python_json "report.json" python3 -m feishu_builder_agent.cli report --case-dir "${CASE_DIR}"
    persist_latest_case_refs "${CASE_DIR}" ""
    print_case_summary "${RUN_LOG_DIR}/report.json"
    ;;
  compile-case-phase1)
    run_spec_generation_if_needed
    ARGS=(python3 -m feishu_builder_agent.cli compile-case-phase1 --case-spec-path "${CASE_SPEC}" --dataset-root "${DATASET_ROOT}")
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      ARGS+=(--dry-run)
    fi
    run_python_json "compile-case-phase1.json" "${ARGS[@]}"
    CASE_DIR="$(json_get "${RUN_LOG_DIR}/compile-case-phase1.json" "case_dir")"
    persist_latest_case_refs "${CASE_DIR}" "${CASE_SPEC}"
    print_case_summary "${RUN_LOG_DIR}/compile-case-phase1.json"
    ;;
  compile-case-phase2)
    run_python_json "compile-case-phase2.json" python3 -m feishu_builder_agent.cli compile-case-phase2 --case-dir "${CASE_DIR}"
    persist_latest_case_refs "${CASE_DIR}" ""
    print_case_summary "${RUN_LOG_DIR}/compile-case-phase2.json"
    ;;
  compile-case-phase3)
    run_python_json "compile-case-phase3.json" python3 -m feishu_builder_agent.cli compile-case-phase3 --case-dir "${CASE_DIR}"
    persist_latest_case_refs "${CASE_DIR}" ""
    print_case_summary "${RUN_LOG_DIR}/compile-case-phase3.json"
    ;;
  full)
    run_spec_generation_if_needed
    ARGS=(python3 -m feishu_builder_agent.cli compile-case-phase1 --case-spec-path "${CASE_SPEC}" --dataset-root "${DATASET_ROOT}")
    if [[ "${DRY_RUN}" -eq 1 ]]; then
      ARGS+=(--dry-run)
    fi
    run_python_json "compile-case-phase1.json" "${ARGS[@]}"
    CASE_DIR="$(json_get "${RUN_LOG_DIR}/compile-case-phase1.json" "case_dir")"
    persist_latest_case_refs "${CASE_DIR}" "${CASE_SPEC}"
    run_python_json "compile-case-phase2.json" python3 -m feishu_builder_agent.cli compile-case-phase2 --case-dir "${CASE_DIR}"
    run_python_json "compile-case-phase3.json" python3 -m feishu_builder_agent.cli compile-case-phase3 --case-dir "${CASE_DIR}"
    print_case_summary "${RUN_LOG_DIR}/compile-case-phase3.json"
    ;;
esac
