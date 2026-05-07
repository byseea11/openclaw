import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, test } from "vitest";

const repoRoot = process.cwd();
const scriptPath = join(
  repoRoot,
  "feishu_task_wiki_benchmark_builder",
  "runtime",
  "openclaw_baseline_eval.mjs",
);
const tempRoots: string[] = [];

function writeJson(path: string, payload: Record<string, unknown>): void {
  writeFileSync(path, `${JSON.stringify(payload, null, 2)}\n`, "utf8");
}

function writeJsonl(path: string, rows: Array<Record<string, unknown>>): void {
  writeFileSync(path, rows.map((row) => JSON.stringify(row)).join("\n") + "\n", "utf8");
}

function messageRow({
  messageId,
  text,
  createTime,
}: {
  messageId: string;
  text: string;
  createTime: number;
}): Record<string, unknown> {
  return {
    message: {
      message_id: messageId,
      chat_id: "oc_fixture",
      thread_id: "",
      root_id: "",
      create_time: String(createTime),
      content: JSON.stringify({ text }),
    },
    benchmark_trace: {
      source_type: "chat",
      source_ref: "chat:main_chat",
    },
  };
}

function collectedRow({
  messageId,
  text,
  beatId,
  turnId,
  officialFileRef = "",
  privateInfoRef = "",
  boundary = "",
}: {
  messageId: string;
  text: string;
  beatId: string;
  turnId: string;
  officialFileRef?: string;
  privateInfoRef?: string;
  boundary?: string;
}): Record<string, unknown> {
  return {
    case_id: "case_fixture_private_info",
    task_id: "FEISHU-666",
    message_id: messageId,
    beat_id: beatId,
    turn_id: turnId,
    turn_kind: "event_bearing",
    session_id: "main_chat",
    message_text: text,
    content_text: text,
    observed_text_without_prefix: text,
    annotation_target: true,
    event_bearing: true,
    official_file_ref: officialFileRef,
    private_info_ref: privateInfoRef,
    task_relevance_boundary: boundary,
    simulated_speaker: { name: "林晨" },
  };
}

function createFixtureCase(): string {
  const root = mkdtempSync(join(tmpdir(), "openclaw-baseline-fixture-"));
  tempRoots.push(root);
  const caseDir = join(root, "cases", "case_fixture_private_info");
  spawnSync(
    "mkdir",
    [
      "-p",
      join(caseDir, "input"),
      join(caseDir, "checks"),
      join(caseDir, "data"),
      join(caseDir, "runtime", "task_wiki_replay"),
    ],
    {
      encoding: "utf8",
    },
  );
  const caseContext = {
    family_id: "private_info_in_official_file",
    benchmark_requirement_name: "Private Info In Official File",
    benchmark_requirement_summary: "区分正式纪要和个人偏好。",
    report_display_name: "Private info fixture",
    capability_under_test: "任务状态记忆",
    why_memory_systems_may_fail: "默认摘要可能混入个人偏好。",
    generation_rules: ["必须包含正式纪要和个人偏好干扰。"],
    required_case_structure: ["正式结论", "个人备注", "纠偏消息"],
    probe_strategy: ["询问正式窗口、blocker 和回滚计划。"],
    expected_good_system_behavior: ["以正式纪要为准，不把个人偏好当任务状态。"],
    case_id: "case_fixture_private_info",
    task_id: "FEISHU-666",
    seed: 7,
    difficulty: "medium",
    comparison_target: "openclaw_original",
    organization: "OpenClaw Test Org",
    team: "QA",
    business_goal: "发布准备",
    scenario_summary: "正式纪要与个人偏好混杂。",
    family_fit_explanation: "验证 private info boundary。",
  };
  const storyPlan = {
    story_id: "story_fixture",
    case_id: "case_fixture_private_info",
    family_id: "private_info_in_official_file",
    task: { task_id: "FEISHU-666", title: "发布准备" },
    actors: [
      { actor_id: "alice", display_name: "林晨", role: "项目负责人" },
      { actor_id: "carol", display_name: "陈雪", role: "研发协作者" },
    ],
    task_actor_layout: { owner: "alice" },
    state_changes: [{ state_id: "state_001", summary: "正式窗口已确认。" }],
    message_beats: [
      {
        beat_id: "beat_001",
        speaker_actor_id: "alice",
        session_id: "main_chat",
        message_intent: "正式纪要确认升级窗口、blocker 和回滚计划。",
        purpose: "正式结论",
      },
      {
        beat_id: "beat_002",
        speaker_actor_id: "carol",
        session_id: "main_chat",
        message_intent: "个人面试偏好干扰。",
        purpose: "个人偏好",
      },
      {
        beat_id: "beat_003",
        speaker_actor_id: "alice",
        session_id: "main_chat",
        message_intent: "重申以正式纪要为准。",
        purpose: "正式结论优先",
      },
    ],
    planned_probe_queries: [
      {
        query:
          "FEISHU-666 的正式升级窗口、blocker 和回滚计划是什么？Carol 的个人偏好是否影响任务？",
        expected_good_behavior:
          "回答正式升级窗口是2026-05-10 22:00 UTC，blocker 是 network config drift，回滚计划已批；Carol 的个人面试偏好不影响任务。",
      },
    ],
  };
  const collectedRows = [
    collectedRow({
      messageId: "om_official",
      text: "正式纪要确认升级窗口2026-05-10 22:00 UTC，blocker为network config drift，回滚计划已批。",
      beatId: "beat_001",
      turnId: "turn_001",
      officialFileRef: "official_file_001",
      boundary: "正式结论",
    }),
    collectedRow({
      messageId: "om_private",
      text: "Carol 周四有个人面试，希望窗口挪到周三前。",
      beatId: "beat_002",
      turnId: "turn_002",
      privateInfoRef: "private_info_001",
      boundary: "个人偏好，不影响任务",
    }),
    collectedRow({
      messageId: "om_correction",
      text: "以正式纪要为准，个人时间不调整任务窗口。",
      beatId: "beat_003",
      turnId: "turn_003",
      officialFileRef: "official_file_001",
      boundary: "正式结论优先",
    }),
  ];
  const ingressRows = [
    messageRow({
      messageId: "om_official",
      text: String(collectedRows[0].message_text),
      createTime: 1,
    }),
    messageRow({
      messageId: "om_private",
      text: String(collectedRows[1].message_text),
      createTime: 2,
    }),
    messageRow({
      messageId: "om_correction",
      text: String(collectedRows[2].message_text),
      createTime: 3,
    }),
  ];
  writeJson(join(caseDir, "input", "case_context.json"), caseContext);
  writeJson(join(caseDir, "input", "story_plan.json"), storyPlan);
  writeJson(join(caseDir, "checks", "pre_annotation_validation_report.json"), {
    case_id: "case_fixture_private_info",
    is_valid: true,
    checks: [],
  });
  writeJsonl(join(caseDir, "data", "collected_messages.jsonl"), collectedRows);
  writeJsonl(join(caseDir, "data", "openclaw_message_ingress.jsonl"), ingressRows);
  writeJson(join(caseDir, "runtime", "task_wiki_replay", "layer_metrics.json"), {
    overall: { status: "passed", health_score: 91 },
    layer1_task_binding: { status: "passed", binding_total: 3 },
    layer2_event_verification: { status: "passed", verified_event_count: 2 },
    layer3_wiki_projection: { status: "passed", projected_task_count: 1 },
  });
  return caseDir;
}

function writeFakeReplayCommand(root: string): string {
  const script = join(root, "fake-openclaw-replay.mjs");
  writeFileSync(
    script,
    `
let body = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => body += chunk);
process.stdin.on("end", () => {
  const input = JSON.parse(body);
  const query = input.query_benchmark.queries[0];
  process.stdout.write(JSON.stringify({
    baseline_mode: "openclaw_real_replay",
    answers: [{
      query_id: query.query_id,
      answer: "正式窗口已确认，证据是 om_official。",
      supporting_message_ids: ["om_official"],
      judge_result: { success: true }
    }]
  }));
});
`.trim() + "\n",
    "utf8",
  );
  return script;
}

function writeAcceptedOnlyReplayCommand(root: string): string {
  const script = join(root, "accepted-only-openclaw-replay.mjs");
  writeFileSync(
    script,
    `
process.stdin.resume();
process.stdin.on("end", () => {
  process.stdout.write(JSON.stringify({
    baseline_mode: "openclaw_real_replay",
    answers: [{
      query_id: "case_fixture_private_info_query_001",
      answer: "{\\"status\\":\\"accepted\\",\\"runId\\":\\"run_fixture\\"}",
      supporting_message_ids: [],
      raw_openclaw_output: { status: "accepted", runId: "run_fixture" }
    }]
  }));
});
`.trim() + "\n",
    "utf8",
  );
  return script;
}

afterEach(() => {
  while (tempRoots.length > 0) {
    const root = tempRoots.pop();
    if (root) {
      rmSync(root, { recursive: true, force: true });
    }
  }
});

describe("openclaw real baseline eval", () => {
  test("generates phase2 gold and baseline outputs", () => {
    const caseDir = createFixtureCase();
    const fakeReplay = writeFakeReplayCommand(caseDir);
    const result = spawnSync(
      "node",
      [scriptPath, "--case-dir", caseDir, "--semantic-gold", "rule", "--json"],
      {
        cwd: repoRoot,
        env: { ...process.env, OPENCLAW_BENCHMARK_REPLAY_COMMAND: `node ${fakeReplay}` },
        encoding: "utf8",
      },
    );
    expect(result.status, `${result.stdout}\n${result.stderr}`).toBe(0);
    const summary = JSON.parse(result.stdout) as {
      baseline_mode: string;
      ingress_count: number;
      query_count: number;
    };
    expect(summary.baseline_mode).toBe("openclaw_real_replay");
    expect(summary.ingress_count).toBe(3);
    expect(summary.query_count).toBe(1);

    const answers = JSON.parse(
      readFileSync(join(caseDir, "runtime", "openclaw_baseline", "answers.json"), "utf8"),
    ) as {
      baseline_mode: string;
      answers: Array<Record<string, unknown>>;
    };
    expect(answers.baseline_mode).toBe("openclaw_real_replay");
    expect(answers.answers).toHaveLength(1);
    expect(answers.answers[0]).toHaveProperty("answer");
    expect(answers.answers[0]).toHaveProperty("supporting_message_ids");
    expect(answers.answers[0]).toHaveProperty("judge_result");

    const report = JSON.parse(
      readFileSync(join(caseDir, "reports", "openclaw_baseline_eval.json"), "utf8"),
    ) as {
      baseline_mode: string;
      gold_generation: { generated_stages: string[] };
      metrics: Record<string, unknown>;
    };
    expect(report.baseline_mode).toBe("openclaw_real_replay");
    expect(report.gold_generation.generated_stages).toEqual([
      "annotation-gold",
      "semantic-gold",
      "query-benchmark",
    ]);
    expect(report.metrics).toHaveProperty("private_info_leak_rate");

    expect(
      readFileSync(join(caseDir, "runtime", "openclaw_baseline", "replay_metadata.json"), "utf8"),
    ).toContain("benchmark_replay_command");
  });

  test("does not import three-layer runtime modules", () => {
    const source = readFileSync(scriptPath, "utf8");
    expect(source).not.toContain("task-banding");
    expect(source).not.toContain("task-events");
    expect(source).not.toContain("task-wiki/projector");
    expect(source).not.toContain("task-wiki/lint");
    expect(source).not.toContain("agent --local");
  });

  test("gateway replay waits for final agent answers", () => {
    const source = readFileSync(scriptPath, "utf8");
    expect(source).toContain("--expect-final");
    expect(source).toContain("finalAssistantVisibleText");
    expect(source).toContain("no_final_answer");
    expect(source).toContain("isAcceptedOnlyGatewayResponse");
  });

  test("accepted-only gateway payload is not treated as a final answer", () => {
    const caseDir = createFixtureCase();
    const fakeReplay = writeAcceptedOnlyReplayCommand(caseDir);
    const result = spawnSync(
      "node",
      [scriptPath, "--case-dir", caseDir, "--semantic-gold", "rule", "--json"],
      {
        cwd: repoRoot,
        env: { ...process.env, OPENCLAW_BENCHMARK_REPLAY_COMMAND: `node ${fakeReplay}` },
        encoding: "utf8",
      },
    );
    expect(result.status, `${result.stdout}\n${result.stderr}`).toBe(0);
    const answers = JSON.parse(
      readFileSync(join(caseDir, "runtime", "openclaw_baseline", "answers.json"), "utf8"),
    ) as {
      answers: Array<{
        answer: string;
        no_final_answer: boolean;
        judge_result: { success: boolean; reasons: string[] };
      }>;
    };
    expect(answers.answers[0].answer).toBe("");
    expect(answers.answers[0].no_final_answer).toBe(true);
    expect(answers.answers[0].judge_result.success).toBe(false);
    expect(answers.answers[0].judge_result.reasons.join(" ")).toContain("未返回 final answer");
  });
});
