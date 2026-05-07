import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { FeishuConfigSchema } from "./config-schema.js";
import { recordFeishuDatasetInboundEvent, recordFeishuDatasetOutboundEvent } from "./dataset-capture.js";

const tempDirs: string[] = [];

afterEach(async () => {
  await Promise.all(
    tempDirs.splice(0).map(async (dir) => {
      await fs.rm(dir, { recursive: true, force: true });
    }),
  );
});

describe("dataset capture", () => {
  it("accepts dataset capture config", () => {
    const parsed = FeishuConfigSchema.parse({
      datasetCapture: {
        enabled: true,
        rootDir: "/tmp/openclaw-office-dataset",
        workspaceId: "ws-1",
        captureId: "capture-1",
      },
    });
    expect(parsed.datasetCapture?.captureId).toBe("capture-1");
  });

  it("records inbound and outbound events into a live capture", async () => {
    const rootDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-feishu-capture-"));
    tempDirs.push(rootDir);
    const cfg = {
      datasetCapture: {
        enabled: true,
        rootDir,
        workspaceId: "ws-1",
        captureId: "capture-1",
      },
    };

    await recordFeishuDatasetInboundEvent({
      cfg,
      accountId: "default",
      event: {
        sender: {
          sender_id: { open_id: "ou_alice" },
          tenant_key: "tenant-1",
        },
        message: {
          message_id: "om_in_1",
          chat_id: "oc_chat_1",
          chat_type: "group",
          message_type: "text",
          content: '{"text":"TASK-1 is blocked by AP-2"}',
          create_time: "1714000000",
          mentions: [{ key: "@bob", id: { open_id: "ou_bob" }, name: "Bob" }],
        },
      },
      ctx: {
        chatId: "oc_chat_1",
        messageId: "om_in_1",
        senderId: "ou_alice",
        senderOpenId: "ou_alice",
        chatType: "group",
        mentionedBot: false,
        content: "TASK-1 is blocked by AP-2",
        contentType: "text",
      },
      senderName: "Alice",
    });

    await recordFeishuDatasetOutboundEvent({
      cfg,
      accountId: "default",
      to: "chat:oc_chat_1",
      chatId: "oc_chat_1",
      messageId: "om_out_1",
      text: "AP-2 approved TASK-1",
      messageType: "post",
    });

    const captureDir = path.join(rootDir, "captures", "capture-1");
    const lines = (await fs.readFile(path.join(captureDir, "office_events.jsonl"), "utf8"))
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line) as Record<string, unknown>);
    expect(lines).toHaveLength(2);
    expect(lines[0].workspace_id).toBe("ws-1");
    expect(lines[0].mentions).toEqual(["ou_bob"]);
    expect(lines[0].relations).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          type: "blocked_by",
          source: "task:TASK-1",
          target: "approval:AP-2",
        }),
      ]),
    );
    expect(lines[1].approval_refs).toEqual(
      expect.arrayContaining([expect.objectContaining({ id: "AP-2", status: "approved" })]),
    );
    const metadata = JSON.parse(await fs.readFile(path.join(captureDir, "capture-metadata.json"), "utf8"));
    expect(metadata.workspace_id).toBe("ws-1");
  });
});
