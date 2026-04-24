import { describe, expect, it } from "vitest";
import {
  extract,
  getDefaultExtractorSystemPrompt,
  getGraphExtractorErrorCode,
  parseGraphJsonBlock,
  parseGraphJsonBlockWithStatus,
  type LLMClient,
} from "./extractor.js";

describe("canonical graph extractor", () => {
  it("prompts the LLM to extract workflow-only graph events", () => {
    const prompt = getDefaultExtractorSystemPrompt();

    expect(prompt).toContain("assigned_owner");
    expect(prompt).toContain("approval_status_updated");
    expect(prompt).toContain("next_action_set");
    expect(prompt).toContain("task-centric workflow events");
    expect(prompt).not.toContain("biographical_fact");
    expect(prompt).not.toContain("preference_fact");
  });

  it("parses the final fenced graph JSON block", () => {
    const events = parseGraphJsonBlock(
      [
        "NO_REPLY",
        "```json",
        '{"events":[{"actor":"Alice","action":"changed_status","object":"task_123","source_ref":"memory/2026-04-15.md#L12-L18"}]}',
        "```",
      ].join("\n"),
    );

    expect(events).toEqual([
      expect.objectContaining({
        actor: "Alice",
        action: "changed_status",
        object: "task_123",
        source_ref: "memory/2026-04-15.md#L12-L18",
      }),
    ]);
  });

  it("returns an empty event list for malformed JSON", () => {
    expect(parseGraphJsonBlock("```json\n{nope\n```")).toEqual([]);
  });

  it("accepts status_before and status_after from fenced graph JSON", () => {
    const parsed = parseGraphJsonBlockWithStatus(
      [
        "NO_REPLY",
        "```json",
        JSON.stringify({
          events: [
            {
              actor: "Alice",
              action: "changed_status",
              object: "task_123",
              status_before: "open",
              status_after: "blocked",
              occurred_at: "2026-04-15",
              source_ref: "memory/2026-04-15.md#L12-L18",
            },
          ],
        }),
        "```",
      ].join("\n"),
    );

    expect(parsed).toMatchObject({
      ok: true,
      events: [
        expect.objectContaining({
          status_before: "open",
          status_after: "blocked",
        }),
      ],
    });
  });

  it("extracts transcript events through the LLM client", async () => {
    const client: LLMClient = {
      async extractGraphEvents() {
        return JSON.stringify({
          events: [
            {
              action: "changed_status",
              object: "task_123",
              status_after: "blocked",
              occurred_at: "2026-04-15",
              source_ref: "#L2-L2",
              confidence: 0.82,
            },
            {
              action: "assigned_owner",
              actor: "Bob",
              object: "task_123",
              occurred_at: "2026-04-15",
              source_ref: "#L3-L3",
              confidence: 0.79,
            },
          ],
        });
      },
    };
    const events = await extract(
      ["# 2026-04-15", "task_123 is blocked", "owner: Bob"].join("\n"),
      "memory/2026-04-15.md#L1-L3",
      client,
    );

    expect(events).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          action: "changed_status",
          object: "task_123",
          status_after: "blocked",
          source_ref: "memory/2026-04-15.md#L2-L2",
          occurred_at: "2026-04-15",
        }),
        expect.objectContaining({
          action: "assigned_owner",
          actor: "Bob",
          object: "task_123",
          source_ref: "memory/2026-04-15.md#L3-L3",
        }),
      ]),
    );
  });

  it("throws unavailable when no LLM client is configured", async () => {
    await expect(extract("FEISHU-231 is blocked", "memory/2026-04-15.md#L1-L1")).rejects.toMatchObject(
      {
        code: "extractor_unavailable",
      },
    );
  });

  it("accepts direct event arrays from the LLM client", async () => {
    const client: LLMClient = {
      async extractGraphEvents() {
        return {
          events: [
            {
              action: "changed_status",
              object: "FEISHU-231",
              status_after: "blocked",
              source_ref: "transcripts/test-transcript.txt#L4-L4",
              confidence: 0.78,
            },
            {
              action: "assigned_owner",
              object: "FEISHU-231",
              actor: "Alice",
              source_ref: "transcripts/test-transcript.txt#L5-L5",
              confidence: 0.75,
            },
          ],
        };
      },
    };
    const events = await extract(
      [
        "[51bcc3e3] assistant: 已记录！我已经创建了今天的记忆文件，并记录了以下信息：",
        "",
        "**FEISHU-231 飞书机器人权限问题**",
        "- **状态**: blocked（阻塞）",
        "- **跟进人**: Alice",
        "",
        "是的，我记得！根据刚才的记录：",
        "- **当前状态**: blocked（阻塞）",
        "- **跟进人**: Alice",
      ].join("\n"),
      "transcripts/test-transcript.txt#L1-L9",
      client,
    );

    expect(events).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          action: "changed_status",
          object: "FEISHU-231",
          status_after: "blocked",
          source_ref: "transcripts/test-transcript.txt#L4-L4",
        }),
        expect.objectContaining({
          action: "assigned_owner",
          object: "FEISHU-231",
          actor: "Alice",
          source_ref: "transcripts/test-transcript.txt#L5-L5",
        }),
      ]),
    );
  });

  it("rejects malformed LLM JSON without falling back to rules", async () => {
    const client: LLMClient = {
      async extractGraphEvents() {
        return "{not-json";
      },
    };
    await expect(
      extract(
        [
          "**FEISHU-231 飞书机器人权限问题**",
          "- **状态**: blocked（阻塞）",
          "- **跟进人**: Bob（从 Alice 接手）",
        ].join("\n"),
        "transcripts/test-transcript.txt#L1-L3",
        client,
      ),
    ).rejects.toMatchObject({
      code: "extractor_invalid_json",
    });
  });

  it("surfaces runtime failures without rules fallback", async () => {
    const client: LLMClient = {
      async extractGraphEvents() {
        throw new Error("gateway timeout after 60000ms");
      },
    };
    await expect(
      extract(
        [
          "**FEISHU-231 飞书机器人权限问题**",
          "- **状态**: blocked（阻塞）",
          "- **跟进人**: Bob（从 Alice 接手）",
        ].join("\n"),
        "transcripts/test-transcript.txt#L1-L3",
        client,
      ),
    ).rejects.toMatchObject({
      code: "extractor_timeout",
    });
  });

  it("rejects empty extractor output", async () => {
    const client: LLMClient = {
      async extractGraphEvents() {
        return "";
      },
    };
    const error = await extract(
      [
        "**FEISHU-231 飞书机器人权限问题**",
        "- **状态**: blocked（阻塞）",
        "- **跟进人**: Bob（从 Alice 接手）",
      ].join("\n"),
      "transcripts/test-transcript.txt#L1-L3",
      client,
    ).catch((err) => err);

    expect(getGraphExtractorErrorCode(error)).toBe("extractor_empty_output");
  });
});
