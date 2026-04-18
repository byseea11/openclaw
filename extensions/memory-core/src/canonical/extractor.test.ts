import { describe, expect, it } from "vitest";
import { extract, parseGraphJsonBlock, parseGraphJsonBlockWithStatus } from "./extractor.js";

describe("canonical graph extractor", () => {
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

  it("extracts rule-based events with precise source refs", async () => {
    const events = await extract(
      [
        "# 2026-04-15",
        "- [ ] task_123 owner: Alice",
        "task_123 is blocked",
        "owner: Bob",
        "Alice decided to ship task_123 tomorrow",
        "status: done",
      ].join("\n"),
      "memory/2026-04-15.md#L1-L6",
    );

    expect(events).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          action: "changed_status",
          object: "task_123",
          status_after: "pending",
          source_ref: "memory/2026-04-15.md#L2-L2",
          occurred_at: "2026-04-15",
        }),
        expect.objectContaining({
          action: "changed_status",
          object: "task_123",
          status_after: "blocked",
          source_ref: "memory/2026-04-15.md#L3-L3",
        }),
        expect.objectContaining({
          action: "assigned_owner",
          actor: "Bob",
          source_ref: "memory/2026-04-15.md#L4-L4",
        }),
        expect.objectContaining({
          action: "decided",
          actor: "Alice",
          object: "ship task_123 tomorrow",
          source_ref: "memory/2026-04-15.md#L5-L5",
        }),
        expect.objectContaining({
          action: "changed_status",
          status_after: "done",
          source_ref: "memory/2026-04-15.md#L6-L6",
        }),
      ]),
    );
  });

  it("extracts markdown status and owner events from real-world Chinese notes", async () => {
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
        expect.objectContaining({
          action: "changed_status",
          object: "FEISHU-231",
          status_after: "blocked",
          source_ref: "transcripts/test-transcript.txt#L8-L8",
        }),
        expect.objectContaining({
          action: "assigned_owner",
          object: "FEISHU-231",
          actor: "Alice",
          source_ref: "transcripts/test-transcript.txt#L9-L9",
        }),
      ]),
    );
  });

  it("extracts owner changes when the new owner includes a Chinese handoff note", async () => {
    const events = await extract(
      [
        "**FEISHU-231 飞书机器人权限问题**",
        "- **状态**: blocked（阻塞）",
        "- **跟进人**: Bob（从 Alice 接手）",
      ].join("\n"),
      "transcripts/test-transcript.txt#L1-L3",
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
