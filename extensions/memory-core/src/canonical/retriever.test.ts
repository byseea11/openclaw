import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { graphHitToMemorySearchResult } from "./prompt.js";
import { search_graph } from "./retriever.js";
import { search_graph_with_plan } from "./retriever.js";
import type { EventRecord } from "./schema.js";
import { CanonicalStore, closeAllCanonicalStores } from "./store.js";

function record(overrides: Partial<EventRecord> = {}): EventRecord {
  return {
    event_id: "evt_task",
    source_type: "memory_file",
    source_ref: "memory/2026-04-15.md#L12-L18",
    occurred_at: "2026-04-15T00:00:00.000Z",
    entity_id: "ent_task",
    actor: "Alice",
    action: "changed_status",
    object: "task_123",
    status_before: null,
    status_after: "blocked",
    session_id: null,
    covered_until_entry_id: null,
    confidence: 0.8,
    extractor_version: "v-test",
    created_at: 1_765_000_000_000,
    ...overrides,
  };
}

async function withP1a<T>(run: () => Promise<T>): Promise<T> {
  const previous = process.env.OPENCLAW_GRAPH_RECALL_P1A;
  process.env.OPENCLAW_GRAPH_RECALL_P1A = "1";
  try {
    return await run();
  } finally {
    if (previous === undefined) {
      delete process.env.OPENCLAW_GRAPH_RECALL_P1A;
    } else {
      process.env.OPENCLAW_GRAPH_RECALL_P1A = previous;
    }
  }
}

async function withWorkflowStateRead<T>(run: () => Promise<T>): Promise<T> {
  const previousWrite = process.env.OPENCLAW_WORKFLOW_STATE_LAYER;
  const previousRead = process.env.OPENCLAW_WORKFLOW_STATE_READ;
  process.env.OPENCLAW_WORKFLOW_STATE_LAYER = "1";
  process.env.OPENCLAW_WORKFLOW_STATE_READ = "1";
  try {
    return await run();
  } finally {
    if (previousWrite === undefined) {
      delete process.env.OPENCLAW_WORKFLOW_STATE_LAYER;
    } else {
      process.env.OPENCLAW_WORKFLOW_STATE_LAYER = previousWrite;
    }
    if (previousRead === undefined) {
      delete process.env.OPENCLAW_WORKFLOW_STATE_READ;
    } else {
      process.env.OPENCLAW_WORKFLOW_STATE_READ = previousRead;
    }
  }
}

function markStaleSource(store: CanonicalStore, sourceId: string): void {
  store.enqueueProjectionInbox({
    source_kind: "transcript",
    source_id: sourceId,
    first_entry_id: "entry-a",
    last_entry_id: "entry-b",
    entries_json: "[]",
    dirty_reason: "test",
    signal_strength: 1,
    strong_event: false,
    created_at: 1_765_000_000_000,
  });
  store.markProjectionFailed(sourceId);
}

describe("canonical graph retriever", () => {
  let rootDir = "";

  beforeEach(async () => {
    rootDir = await fs.mkdtemp(path.join(os.tmpdir(), "openclaw-canonical-retriever-"));
  });

  afterEach(async () => {
    await closeAllCanonicalStores();
    await fs.rm(rootDir, { recursive: true, force: true });
  });

  it("returns state and event hits with source refs", async () => {
    const store = new CanonicalStore("main", path.join(rootDir, "main.graph.sqlite"));
    await store.upsertEvents([
      record(),
      record({
        event_id: "evt_other",
        entity_id: "ent_other",
        object: "task_999",
        source_ref: "memory/2026-04-01.md#L2-L2",
        occurred_at: "2026-04-01T00:00:00.000Z",
        created_at: 1_765_000_000_100,
      }),
    ]);
    await store.refreshEntityStates([
      record(),
      record({ event_id: "evt_other", entity_id: "ent_other", object: "task_999" }),
    ]);

    const hits = await search_graph(store, "task_123", 5);

    expect(hits).toEqual([
      expect.objectContaining({
        type: "state",
        entity_id: "ent_task",
        source_ref: "memory/2026-04-15.md#L12-L18",
      }),
      expect.objectContaining({
        type: "event",
        entity_id: "ent_task",
        source_ref: "memory/2026-04-15.md#L12-L18",
      }),
    ]);
    store.close();
  });

  it("uses KG edges before event fallback for owner queries", async () => {
    const store = new CanonicalStore("main", path.join(rootDir, "main.graph.sqlite"));
    await store.persistCanonicalBatch([
      record({
        action: "assigned_owner",
        object: "FEISHU-231",
        object_type: "task",
      }),
    ]);

    const hits = await search_graph(store, "who owns FEISHU-231", 5);

    expect(hits[0]).toMatchObject({
      type: "edge",
      source_ref: "memory/2026-04-15.md#L12-L18",
      snippet_structured: expect.objectContaining({
        relation: "owned_by",
        query_class: "state",
        planner: "state_planner",
        graph_freshness: "fresh",
      }),
    });
    store.close();
  });

  it("keeps P1a behind an internal gate", async () => {
    const store = new CanonicalStore("main", path.join(rootDir, "main.graph.sqlite"));
    await store.persistCanonicalBatch([
      record({
        action: "assigned_owner",
        object: "FEISHU-231",
        object_type: "task",
      }),
    ]);

    const { plannerResult } = await search_graph_with_plan(store, "who owns FEISHU-231", 5);

    expect(plannerResult).toBeNull();
    store.close();
  });

  it("groups state evidence with four-state freshness when P1a is enabled", async () => {
    await withP1a(async () => {
      const store = new CanonicalStore("main", path.join(rootDir, "main.graph.sqlite"));
      store.markProjectionDrained({ sourceId: "fresh-source", coveredUntilEntryId: "entry-1" });
      markStaleSource(store, "stale-source");
      await store.persistCanonicalBatch([
        record({
          event_id: "evt_fresh",
          entity_id: "ent_feishu_100",
          actor: "Alice",
          action: "assigned_owner",
          object: "FEISHU-100",
          object_type: "task",
          session_id: "fresh-source",
          source_ref: "memory/2026-04-15.md#L12-L12",
        }),
        record({
          event_id: "evt_stale",
          entity_id: "ent_feishu_100",
          actor: "Alice",
          action: "assigned_owner",
          object: "FEISHU-100",
          object_type: "task",
          session_id: "stale-source",
          source_ref: "memory/2026-04-15.md#L13-L13",
          created_at: 1_765_000_000_100,
        }),
        record({
          event_id: "evt_unknown",
          entity_id: "ent_feishu_101",
          actor: "Bob",
          action: "assigned_owner",
          object: "FEISHU-101",
          object_type: "task",
          session_id: null,
          source_ref: "memory/2026-04-15.md#L14-L14",
          created_at: 1_765_000_000_200,
        }),
      ]);

      const mixed = await search_graph_with_plan(store, "who owns FEISHU-100", 5);
      expect(mixed.plannerResult?.main_groups[0]).toMatchObject({
        group_type: "state",
        freshness: "mixed",
      });
      expect(mixed.plannerResult?.freshness_decisions).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ freshness: "fresh", source_id: "fresh-source" }),
          expect.objectContaining({ freshness: "stale", source_id: "stale-source" }),
        ]),
      );

      const unknown = await search_graph_with_plan(store, "who owns FEISHU-101", 5);
      expect(unknown.plannerResult?.main_groups[0]).toMatchObject({
        freshness: "unknown",
      });
      store.close();
    });
  });

  it("uses bounded fallback when resolution is unresolved", async () => {
    await withP1a(async () => {
      const store = new CanonicalStore("main", path.join(rootDir, "main.graph.sqlite"));
      await store.upsertEvents([
        record({
          event_id: "evt_fallback",
          object: "unresolved customer escalation",
          action: "changed_status",
          source_ref: "memory/2026-04-15.md#L20-L20",
        }),
      ]);
      await store.refreshEntityStates([
        record({ event_id: "evt_fallback", object: "unresolved customer escalation" }),
      ]);

      const { hits, plannerResult } = await search_graph_with_plan(
        store,
        "unresolved customer escalation",
        5,
      );

      expect(plannerResult).toMatchObject({
        resolution_status: "unresolved",
        fallback_reason: expect.arrayContaining(["groups_insufficient", "resolution_unresolved"]),
      });
      expect(plannerResult?.fallback_hits.length).toBeLessThanOrEqual(2);
      expect(hits.some((hit) => hit.snippet_structured.planner === "fts_fallback")).toBe(true);
      store.close();
    });
  });

  it("caps list groups by relation and target", async () => {
    await withP1a(async () => {
      const store = new CanonicalStore("main", path.join(rootDir, "main.graph.sqlite"));
      const records = Array.from({ length: 8 }, (_, index) =>
        record({
          event_id: `evt_owner_${index}`,
          entity_id: "ent_feishu_200",
          actor: `Owner${index}`,
          action: "assigned_owner",
          object: "FEISHU-200",
          object_type: "task",
          source_ref: `memory/2026-04-15.md#L${30 + index}-L${30 + index}`,
          created_at: 1_765_000_000_000 + index,
        }),
      );
      await store.persistCanonicalBatch(records);

      const { hits, plannerResult } = await search_graph_with_plan(
        store,
        "list owners for FEISHU-200",
        10,
      );

      expect(plannerResult?.main_groups).toHaveLength(4);
      expect(hits.length).toBeLessThanOrEqual(6);
      expect(
        plannerResult?.main_groups.every((group) => group.group_type === "relation_list"),
      ).toBe(true);
      store.close();
    });
  });

  it("marks ambiguous entity resolution and falls back without hard grouping", async () => {
    await withP1a(async () => {
      const store = new CanonicalStore("main", path.join(rootDir, "main.graph.sqlite"));
      await store.persistCanonicalBatch([
        record({
          event_id: "evt_alpha_a",
          entity_id: "ent_alpha_a",
          actor: "Alice",
          action: "assigned_owner",
          object: "Project Alpha",
          object_type: "project",
          source_ref: "memory/2026-04-15.md#L40-L40",
        }),
        record({
          event_id: "evt_alpha_b",
          entity_id: "ent_alpha_b",
          actor: "Bob",
          action: "assigned_owner",
          object: "Project Alpha",
          object_type: "project",
          source_ref: "memory/2026-04-15.md#L41-L41",
        }),
      ]);

      const { plannerResult } = await search_graph_with_plan(store, "Project Alpha owner", 5);

      expect(plannerResult).toMatchObject({
        resolution_status: "ambiguous",
        resolved_entity_ids: [],
        fallback_reason: expect.arrayContaining(["resolution_ambiguous"]),
      });
      expect(plannerResult?.main_groups).toEqual([]);
      store.close();
    });
  });

  it("preserves scheduled_for and decision approval conflict groups", async () => {
    await withP1a(async () => {
      const store = new CanonicalStore("main", path.join(rootDir, "main.graph.sqlite"));
      await store.persistCanonicalBatch([
        record({
          event_id: "evt_schedule_a",
          entity_id: "ent_meeting",
          actor: "Alice",
          action: "scheduled_meeting",
          object: "Launch review meeting",
          object_type: "meeting",
          occurred_at: "2026-04-20T00:00:00.000Z",
          source_ref: "memory/2026-04-20.md#L1-L1",
        }),
        record({
          event_id: "evt_schedule_b",
          entity_id: "ent_meeting",
          actor: "Alice",
          action: "scheduled_meeting",
          object: "Launch review meeting",
          object_type: "meeting",
          occurred_at: "2026-04-21T00:00:00.000Z",
          source_ref: "memory/2026-04-21.md#L1-L1",
        }),
        record({
          event_id: "evt_decision_approved",
          entity_id: "ent_decision",
          actor: "Alice",
          action: "approved_decision",
          object: "Launch approval decision",
          object_type: "decision",
          status_after: "approved",
          source_ref: "memory/2026-04-21.md#L2-L2",
        }),
        record({
          event_id: "evt_decision_rejected",
          entity_id: "ent_decision",
          actor: "Bob",
          action: "rejected_decision",
          object: "Launch approval decision",
          object_type: "decision",
          status_after: "rejected",
          source_ref: "memory/2026-04-21.md#L3-L3",
        }),
      ]);

      const schedule = await search_graph_with_plan(store, "timeline Launch review meeting", 8);
      expect(schedule.plannerResult?.conflict_groups).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ conflict_type: "scheduled_for_conflict" }),
        ]),
      );

      const decision = await search_graph_with_plan(store, "timeline Launch approval decision", 8);
      expect(decision.plannerResult?.conflict_groups).toEqual(
        expect.arrayContaining([
          expect.objectContaining({ conflict_type: "decision_approval_conflict" }),
        ]),
      );
      store.close();
    });
  });

  it("keeps weak relations out of main evidence when strong evidence exists and renders groups compatibly", async () => {
    await withP1a(async () => {
      const store = new CanonicalStore("main", path.join(rootDir, "main.graph.sqlite"));
      await store.persistCanonicalBatch([
        record({
          event_id: "evt_strong_owner",
          entity_id: "ent_feishu_300",
          actor: "Alice",
          action: "assigned_owner",
          object: "FEISHU-300",
          object_type: "task",
          source_ref: "memory/2026-04-15.md#L50-L50",
        }),
        record({
          event_id: "evt_weak_note",
          entity_id: "ent_feishu_300",
          actor: "Alice",
          action: "mentioned",
          object: "FEISHU-300 came up in planning",
          object_type: "task",
          source_ref: "memory/2026-04-15.md#L51-L51",
        }),
      ]);

      const { hits, plannerResult } = await search_graph_with_plan(store, "who owns FEISHU-300", 5);
      const first = hits[0];

      expect(plannerResult?.main_groups[0]?.relation).not.toBe("about");
      expect(plannerResult?.main_groups[0]?.relation).not.toBe("mentions");
      expect(first?.snippet_structured).toMatchObject({
        group_type: "state",
        evidence_group: expect.objectContaining({
          group_type: "state",
        }),
      });
      expect(first ? graphHitToMemorySearchResult(first) : null).toMatchObject({
        corpus: "graph",
        path: "memory/2026-04-15.md",
      });
      store.close();
    });
  });

  it("prefers workflow state rows for state queries when workflow read is enabled", async () => {
    await withP1a(async () => {
      await withWorkflowStateRead(async () => {
        const store = new CanonicalStore("main", path.join(rootDir, "main.graph.sqlite"));
        await store.persistCanonicalBatch([
          record({
            event_id: "evt_workflow_owner",
            entity_id: "ent_feishu_500",
            actor: "Alice",
            action: "assigned_owner",
            object: "FEISHU-500",
            object_type: "task",
            status_after: "blocked",
            source_type: "transcript",
            session_id: "session-a",
            source_ref: "transcripts/session-a.txt#L10-L10",
          }),
        ]);

        const { plannerResult } = await search_graph_with_plan(store, "who owns FEISHU-500", 5);

        expect(plannerResult?.main_groups[0]).toMatchObject({
          group_type: "state",
          relation: "workflow_state",
        });
        store.close();
      });
    });
  });
});
