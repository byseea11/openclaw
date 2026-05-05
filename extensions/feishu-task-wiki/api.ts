import { createRequire } from "node:module";

import type { OpenClawPluginApi } from "openclaw/plugin-sdk/channel-entry-contract";
import type { ChannelPlugin } from "openclaw/plugin-sdk/core";

export * from "./openclaw-lark/src/task-banding/task-binding.ts";
export * from "./openclaw-lark/src/task-banding/task-routing.ts";

const require = createRequire(import.meta.url);

export interface ProjectSessionWikiParams {
  sessionDir: string;
}

export interface ProjectTaskIndexParams {
  taskRootDir: string;
  sessionState: Record<string, unknown>;
}

export interface ProjectTaskWikiParams {
  taskRootDir: string;
  sessionState: Record<string, unknown>;
}

export interface UpdateTaskWikiFromVerifiedEventsParams {
  sessionDir: string;
}

export interface TaskWikiLintParams {
  taskRootDir: string;
  appendLog?: boolean;
}

export interface RevokeSourceSessionParams {
  taskRootDir: string;
  sourceSessionId: string;
  reason?: string;
}

export interface InvalidateSessionEventParams {
  taskRootDir: string;
  eventId: string;
  reason?: string;
}

export interface SupersedeSessionEventsParams {
  taskRootDir: string;
  supersedingEventId: string;
  supersededEventIds: string[];
  reason?: string;
}

export interface SessionProjectionResult {
  sessionState: Record<string, unknown>;
  changedBlockIds?: string[];
  removedBlockIds?: string[];
  taskRootDir?: string;
}

export interface TaskWikiUpdateResult {
  changedBlockIds: string[];
  removedBlockIds: string[];
  sessionState: Record<string, unknown>;
  indexState: Record<string, unknown>;
  taskWikiState: Record<string, unknown>;
}

export interface TaskWikiLintResult {
  version: number;
  generated_at: string;
  orphan_event_count: number;
  missing_evidence_ref_count: number;
  stale_claim_count: number;
  unresolved_objection_count: number;
  overdue_commitment_count: number;
  open_conflict_count: number;
  orphan_block_count: number;
  findings: Record<string, unknown>;
}

export interface ForgettingUpdateResult {
  updatedPages: string[];
}

const taskWikiProjector = require("./openclaw-lark/src/task-wiki/projector.js") as {
  projectSessionWiki: (params: ProjectSessionWikiParams) => Promise<SessionProjectionResult>;
  projectTaskIndex: (params: ProjectTaskIndexParams) => Promise<Record<string, unknown>>;
  projectTaskWiki: (params: ProjectTaskWikiParams) => Promise<Record<string, unknown>>;
  updateTaskWikiFromVerifiedEvents: (
    params: UpdateTaskWikiFromVerifiedEventsParams,
  ) => Promise<TaskWikiUpdateResult>;
};

const taskWikiLint = require("./openclaw-lark/src/task-wiki/lint.js") as {
  runTaskWikiLint: (params: TaskWikiLintParams) => Promise<TaskWikiLintResult>;
};

const taskWikiForgetting = require("./openclaw-lark/src/task-wiki/forgetting.js") as {
  revokeSourceSession: (
    params: RevokeSourceSessionParams,
  ) => Promise<ForgettingUpdateResult & { sourceSessionId: string }>;
  invalidateSessionEvent: (
    params: InvalidateSessionEventParams,
  ) => Promise<ForgettingUpdateResult & { eventId: string }>;
  supersedeSessionEvents: (
    params: SupersedeSessionEventsParams,
  ) => Promise<
    ForgettingUpdateResult & { supersedingEventId: string; supersededEventIds: string[] }
  >;
};

export const projectSessionWiki = taskWikiProjector.projectSessionWiki;
export const projectTaskIndex = taskWikiProjector.projectTaskIndex;
export const projectTaskWiki = taskWikiProjector.projectTaskWiki;
export const updateTaskWikiFromVerifiedEvents =
  taskWikiProjector.updateTaskWikiFromVerifiedEvents;
export const runTaskWikiLint = taskWikiLint.runTaskWikiLint;
export const revokeSourceSession = taskWikiForgetting.revokeSourceSession;
export const invalidateSessionEvent = taskWikiForgetting.invalidateSessionEvent;
export const supersedeSessionEvents = taskWikiForgetting.supersedeSessionEvents;

export const feishuTaskWikiChannelPlugin = require("./openclaw-lark/src/channel/plugin.js")
  .feishuPlugin as ChannelPlugin;

export function registerFeishuTaskWikiFull(api: OpenClawPluginApi) {
  const loaded = require("./openclaw-lark/index.js");
  const plugin = (loaded?.default ?? loaded) as { register?: (api: OpenClawPluginApi) => void };
  if (typeof plugin?.register !== "function") {
    throw new Error("feishu-task-wiki runtime entry is missing register(api)");
  }

  plugin.register({
    ...api,
    registerChannel() {
      // Bundled channel entry already registers the channel plugin.
    },
  });
}
