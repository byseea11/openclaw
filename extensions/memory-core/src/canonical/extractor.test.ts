import { describe, expect, it } from "vitest";
import {
  extract,
  getDefaultExtractorSystemPrompt,
  getGraphExtractorErrorCode,
  parseGraphJsonBlock,
  parseGraphJsonBlockWithStatus,
  type DecisionExtractionEnvelope,
  type LLMClient,
} from "./extractor.js";

describe("canonical decision extractor", () => {
  it("prompts the LLM to extract quote-grounded decision claims", () => {
    const prompt = getDefaultExtractorSystemPrompt();
    expect(prompt).toContain("quote-grounded decision memory events");
    expect(prompt).toContain("decision_axis_key");
    expect(prompt).toContain("evidence_quote");
    expect(prompt).toContain("Allowed claim_field values: conclusion, rationale, objection, stage, time_point.");
    expect(prompt).toContain("Use CORE to decide whether to create new decision events.");
    expect(prompt).toContain("Do not generate a new decision event from CONTEXT alone.");
    expect(prompt).toContain("Do not use CURRENT_STATE_CONTEXT as evidence.");
    expect(prompt).not.toContain("assigned_owner");
  });

  it("parses the final fenced decision JSON block", () => {
    const extraction = parseGraphJsonBlock(
      [
        "```json",
        JSON.stringify({
          should_extract: true,
          topic_ref: "topic:task:FEISHU-231:release_date",
          topic_anchors_json: { task_refs: ["task:FEISHU-231"] },
          decision_axis_key: "release_date",
          decision_axis_text: "Whether the release date is confirmed",
          decision_axis_instance_id: null,
          claims: [
            {
              claim_field: "time_point",
              claim_text: "5 月 5 日不是已确认发布日期",
              claim_value_json: {
                date: "2026-05-05",
                role: "target_date",
                core_entry_id: "core-1",
                supporting_context_quotes: [
                  {
                    quote: "目标发布时间暂定 5 月 5 日",
                    entry_id: "ctx-1",
                    source: "context",
                  },
                ],
              },
              evidence_quote: "5 月 5 日不是已确认发布日期",
              confidence: 0.91,
            },
          ],
        }),
        "```",
      ].join("\n"),
    );

    expect(extraction).toMatchObject({
      should_extract: true,
      decision_axis_key: "release_date",
      claims: [
        expect.objectContaining({
          claim_field: "time_point",
          evidence_quote: "5 月 5 日不是已确认发布日期",
          claim_value_json: expect.objectContaining({
            core_entry_id: "core-1",
            supporting_context_quotes: [
              expect.objectContaining({
                quote: "目标发布时间暂定 5 月 5 日",
                entry_id: "ctx-1",
                source: "context",
              }),
            ],
          }),
        }),
      ],
    });
  });

  it("returns should_extract=false for malformed JSON", () => {
    expect(parseGraphJsonBlock("```json\n{nope\n```")).toMatchObject({
      should_extract: false,
      claims: [],
    });
  });

  it("extracts decision claims through the LLM client", async () => {
    const client: LLMClient = {
      async extractGraphEvents() {
        return {
          extraction: {
            should_extract: true,
            topic_ref: "topic:task:FEISHU-231:release_date",
            topic_anchors_json: { task_refs: ["task:FEISHU-231"] },
            decision_axis_key: "release_date",
            decision_axis_text: "Whether the release date is confirmed",
            decision_axis_instance_id: null,
            claims: [
              {
                claim_field: "time_point",
                claim_text: "5 月 5 日不是已确认发布日期",
                claim_value_json: {
                  date: "2026-05-05",
                  role: "target_date",
                  modality: "not_confirmed",
                },
                evidence_quote: "5 月 5 日不是已确认发布日期",
                confidence: 0.93,
              },
              {
                claim_field: "rationale",
                claim_text: "迁移窗口还没锁定",
                claim_value_json: { reason_type: "risk_or_blocker" },
                evidence_quote: "迁移窗口还没锁定",
                confidence: 0.89,
              },
            ],
          },
        };
      },
    };
    const extraction = await extract(
      "FEISHU-231 这周先按 5 月 5 日推进，但 5 月 5 日不是已确认发布日期，因为迁移窗口还没锁定。",
      "transcripts/test.txt#L1-L1",
      client,
    );
    expect(extraction).toMatchObject({
      should_extract: true,
      decision_axis_key: "release_date",
    });
    expect(extraction.claims).toHaveLength(2);
  });

  it("renders structured envelopes with separate context and core sections", async () => {
    const requests: Array<{ prompt: string }> = [];
    const client: LLMClient = {
      async extractGraphEvents(request) {
        requests.push({ prompt: request.prompt });
        return {
          extraction: {
            should_extract: false,
            topic_ref: null,
            topic_anchors_json: null,
            decision_axis_key: null,
            decision_axis_text: null,
            decision_axis_instance_id: null,
            claims: [],
          },
        };
      },
    };
    const envelope: DecisionExtractionEnvelope = {
      anchors: {
        task_refs: ["task:FEISHU-231"],
        thread_ids: ["thread-root"],
        doc_refs: [],
        project_names: [],
        source_chat_ids: ["chat-1"],
      },
      current_state_context: {
        topic_ref: "topic:task:FEISHU-231:release_date",
        decision_axis_key: "release_date",
        active_conclusion: "当前不把 5 月 5 日当成确认日期。",
        active_time_points: ["5 月 5 日不是已确认发布日期"],
        active_rationales: ["迁移窗口还没锁定"],
        active_objections: [],
      },
      context_entries: [
        {
          entry_id: "ctx-1",
          parent_id: null,
          role: "user",
          content: "FEISHU-231 目标发布时间暂定 5 月 5 日。",
          timestamp: "2026-04-17T00:00:00.000Z",
        },
      ],
      core_entries: [
        {
          entry_id: "core-1",
          parent_id: "ctx-1",
          role: "assistant",
          content: "这个日期先别说死。",
          timestamp: "2026-04-17T00:01:00.000Z",
        },
      ],
    };

    await extract(envelope, "transcripts/test.txt#L1-L2", client);

    expect(requests).toHaveLength(1);
    expect(requests[0].prompt).toContain("[CURRENT_STATE_CONTEXT]");
    expect(requests[0].prompt).toContain("[CONTEXT]");
    expect(requests[0].prompt).toContain("[CORE]");
    expect(requests[0].prompt).toContain("Extract new claims only from CORE.");
    expect(requests[0].prompt).toContain("Use CONTEXT only for reference resolution.");
    expect(requests[0].prompt).toContain("Do not generate a new decision event from CONTEXT alone.");
    expect(requests[0].prompt).toContain("Do not use CURRENT_STATE_CONTEXT as evidence.");
  });

  it("throws unavailable when no LLM client is configured", async () => {
    await expect(
      extract("FEISHU-231 先按 5 月 5 日推进", "memory/2026-04-15.md#L1-L1"),
    ).rejects.toMatchObject({
      code: "extractor_unavailable",
    });
  });

  it("rejects malformed LLM JSON without fallback", async () => {
    const client: LLMClient = {
      async extractGraphEvents() {
        return "{not-json";
      },
    };
    await expect(
      extract("5 月 5 日不是已确认发布日期", "transcripts/test.txt#L1-L1", client),
    ).rejects.toMatchObject({
      code: "extractor_invalid_json",
    });
  });

  it("surfaces runtime failures without fallback", async () => {
    const client: LLMClient = {
      async extractGraphEvents() {
        throw new Error("gateway timeout after 60000ms");
      },
    };
    await expect(
      extract("迁移窗口还没锁定", "transcripts/test.txt#L1-L1", client),
    ).rejects.toMatchObject({
      code: "extractor_timeout",
    });
  });

  it("exposes extractor error codes", async () => {
    const client: LLMClient = {
      async extractGraphEvents() {
        return "";
      },
    };
    const error = await extract("FEISHU-231", "transcripts/test.txt#L1-L1", client).catch(
      (value) => value,
    );
    expect(getGraphExtractorErrorCode(error)).toBe("extractor_empty_output");
  });

  it("returns parse status metadata", () => {
    expect(
      parseGraphJsonBlockWithStatus(
        JSON.stringify({
          should_extract: false,
          topic_ref: null,
          topic_anchors_json: null,
          decision_axis_key: null,
          decision_axis_text: null,
          decision_axis_instance_id: null,
          claims: [],
        }),
      ),
    ).toMatchObject({
      ok: true,
      extraction: { should_extract: false, claims: [] },
    });
  });
});
