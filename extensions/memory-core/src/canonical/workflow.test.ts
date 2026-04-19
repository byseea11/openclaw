import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { EventRecord, WorkflowUpdate } from "./schema.js";
import { CanonicalStore, closeAllCanonicalStores } from "./store.js";

function record(overrides: Partial<EventRecord> = {}): EventRecord {
  return {
    event_id: "evt_task",
    source_type: "transcript",
    source_ref: "transcripts/session-a.txt#L1-L1",
    occurred_at: "2026-04-15T00:00:00.000Z",
    entity_id: "ent_task",
    actor: "Alice",
    action: "assigned_owner",
    object: "FEISHU-231",
    object_type: "task",
    status_before: null,
    status_after: "blocked",
    session_id: "session-a",
    covered_until_entry_id: "entry-1",
    confidence: 0.82,
    extractor_version: "v-test",
    created_at: 1_765_000_000_000,
    ...overrides,
  };
}

async function withWorkflowWrite<T>(run: () => Promise<T>): Promise<T> {
  const previous = process.env.OPENCLAW_WORKFLOW_STATE_LAYER;
  process.env.OPENCLAW_WORKFLOW_STATE_LAYER = "1";
  try {
    return await run();
  } finally {
    if (previous === undefined) {
      delete process.env.OPENCLAW_WORKFLOW_STATE_LAYER;
    } else {
      process.env.OPENCLAW_WORKFLOW_STATE_LAYER = previous;
    }
  }
}

describe("workflow state projection", () => {
  let rootDir = "";

  beforeEach(async () => {
    rootDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-workflow-state-"));
  });

  afterEach(async () => {
    await closeAllCanonicalStores();
    await fs.rm(rootDir, { recursive: true, force: true });
  });

  it("projects workflow state from canonical batches", async () => {
    await withWorkflowWrite(async () => {
      const store = new CanonicalStore("main", path.join(rootDir, "main.graph.sqlite"));
      const persisted = await store.persistCanonicalBatch([record()]);

      expect(persisted.workflowResults).toEqual([
        expect.objectContaining({
          object_type: "task",
          object_id: "ent_task",
          admission: "current_state_patch",
        }),
      ]);
      expect(store.getWorkflowState("task", "ent_task")).toMatchObject({
        object_type: "task",
        object_id: "ent_task",
        stage: "blocked",
        blocker_status: "blocked",
        blocker_reason: "FEISHU-231",
        last_event_id: "evt_task",
        supporting_event_ids: ["evt_task"],
      });
      expect(store.getStatus()).toMatchObject({
        workflowStatesTotal: 1,
      });
      store.close();
    });
  });

  it("rejects ambiguous workflow updates without creating a row", async () => {
    const store = new CanonicalStore("main", path.join(rootDir, "main.graph.sqlite"));
    const result = await store.applyWorkflowUpdate({
      object_type: "task",
      object_id: "ent_task",
      occurred_at: "2026-04-15T00:00:00.000Z",
      source: {
        source_kind: "transcript",
        source_ref: "transcripts/session-a.txt#L1-L1",
        session_id: "session-a",
      },
      patch: {
        set: {
          stage: "blocked",
        },
      },
      evidence: {
        event_id: "evt_ambiguous",
        confidence: 0.9,
        relation_strength: "strong",
        resolution_status: "ambiguous",
      },
      derived: {
        canonical_entity_id: "ent_task",
        canonical_entity_type: "task",
        workflow_type_source: "canonical_type",
      },
    } satisfies WorkflowUpdate);

    expect(result).toMatchObject({
      admission: "reject",
      applied: false,
    });
    expect(store.getWorkflowState("task", "ent_task")).toBeNull();
    store.close();
  });

  it("does not allow one canonical entity to create multiple workflow object types", async () => {
    await withWorkflowWrite(async () => {
      const store = new CanonicalStore("main", path.join(rootDir, "main.graph.sqlite"));
      const results = await store.persistCanonicalBatch([
        record({
          event_id: "evt_task_state",
          entity_id: "ent_shared",
          object: "FEISHU-400",
          object_type: "task",
          status_after: "blocked",
        }),
        record({
          event_id: "evt_task_approval",
          entity_id: "ent_shared",
          action: "approved_decision",
          object: "FEISHU-400 approval",
          object_type: "decision",
          status_after: "approved",
        }),
      ]);

      expect(results.workflowResults.every((result) => result.admission === "reject")).toBe(true);
      expect(store.listWorkflowStates()).toEqual([]);
      store.close();
    });
  });

  it("applies batch updates deterministically regardless of input order", async () => {
    await withWorkflowWrite(async () => {
      const forward = new CanonicalStore("forward", path.join(rootDir, "forward.graph.sqlite"));
      const reverse = new CanonicalStore("reverse", path.join(rootDir, "reverse.graph.sqlite"));
      const events = [
        record({
          event_id: "evt_owner_transcript",
          actor: "Alice",
          source_type: "transcript",
          occurred_at: "2026-04-15T09:00:00.000Z",
        }),
        record({
          event_id: "evt_owner_tool",
          actor: "Bob",
          source_type: "tool_result",
          occurred_at: "2026-04-15T09:00:00.000Z",
        }),
      ];

      await forward.persistCanonicalBatch(events);
      await reverse.persistCanonicalBatch(events.toReversed());

      const forwardRow = forward.getWorkflowState("task", "ent_task");
      const reverseRow = reverse.getWorkflowState("task", "ent_task");
      expect(forwardRow).toMatchObject(reverseRow ?? {});
      expect(forwardRow?.owner_entity_id).toBe(
        reverse.resolveEntityCandidates("Bob")[0]?.entity_id,
      );
      forward.close();
      reverse.close();
    });
  });

  it("keeps workflow evidence idempotent without a ledger", async () => {
    await withWorkflowWrite(async () => {
      const store = new CanonicalStore("main", path.join(rootDir, "main.graph.sqlite"));
      await store.persistCanonicalBatch([record()]);
      await store.persistCanonicalBatch([record()]);

      expect(store.getWorkflowState("task", "ent_task")).toMatchObject({
        supporting_event_ids: ["evt_task"],
      });
      store.close();
    });
  });

  it("supports graph-only and graph+workflow backfill modes", async () => {
    await withWorkflowWrite(async () => {
      const graphOnlyStore = new CanonicalStore(
        "graph-only",
        path.join(rootDir, "graph-only.graph.sqlite"),
      );
      await graphOnlyStore.upsertEvents([record({ source_type: "memory_file", session_id: null })]);
      await graphOnlyStore.backfillGraphObjectsFromEvents({ includeWorkflowState: false });
      expect(graphOnlyStore.listWorkflowStates()).toEqual([]);
      graphOnlyStore.close();

      const fullStore = new CanonicalStore("full", path.join(rootDir, "full.graph.sqlite"));
      await fullStore.upsertEvents([record({ source_type: "memory_file", session_id: null })]);
      await expect(
        fullStore.backfillGraphObjectsFromEvents({ includeWorkflowState: true }),
      ).resolves.toMatchObject({
        workflowUpdates: 1,
      });
      expect(fullStore.getWorkflowState("task", "ent_task")).toMatchObject({
        object_id: "ent_task",
      });
      fullStore.close();
    });
  });
});
