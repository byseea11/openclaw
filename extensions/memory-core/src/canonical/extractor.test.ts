import { describe, expect, it } from "vitest";
import {
  extract,
  getDefaultExtractorSystemPrompt,
  parseGraphJsonBlock,
  parseGraphJsonBlockWithStatus,
  type LLMClient,
} from "./extractor.js";

describe("canonical graph extractor", () => {
  it("prompts the LLM to extract durable conversational memory facts", () => {
    const prompt = getDefaultExtractorSystemPrompt();

    expect(prompt).toContain("biographical_fact");
    expect(prompt).toContain("preference_fact");
    expect(prompt).toContain("Do not require a ticket id or task id");
    expect(prompt).toContain("Session date: YYYY-MM-DD");
    expect(prompt).toContain("omit `occurred_at`");
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

  it("accepts status_before and status_after from flush JSON", () => {
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

  it("falls back to rules when the LLM extractor fails", async () => {
    const client: LLMClient = {
      async extractGraphEvents() {
        throw new Error("boom");
      },
    };
    const events = await extract(
      [
        "**FEISHU-231 飞书机器人权限问题**",
        "- **状态**: blocked（阻塞）",
        "- **跟进人**: Bob（从 Alice 接手）",
      ].join("\n"),
      "transcripts/test-transcript.txt#L1-L3",
      client,
    );

    expect(events).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          action: "assigned_owner",
          object: "FEISHU-231",
          actor: "Bob",
          source_ref: "transcripts/test-transcript.txt#L3-L3",
        }),
      ]),
    );
  });
});
