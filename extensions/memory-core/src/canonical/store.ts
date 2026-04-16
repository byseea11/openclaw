import os from "node:os";
import path from "node:path";
import type { DatabaseSync, SQLInputValue } from "node:sqlite";
import {
  createSubsystemLogger,
  resolveStateDir,
} from "openclaw/plugin-sdk/memory-core-host-engine-foundation";
import { openMemoryDatabaseAtPath } from "../memory/manager-db.js";
import { reduce } from "./reducer.js";
import {
  CANONICAL_SCHEMA_SQL,
  CANONICAL_SCHEMA_VERSION,
  EXTRACTOR_VERSION,
  type EntityState,
  type EventRecord,
} from "./schema.js";

const log = createSubsystemLogger("memory");
const stores = new Map<string, CanonicalStore>();

type EventRow = EventRecord & { fts_score?: number };

function graphDbPathForAgent(agentId: string): string {
  return path.join(resolveStateDir(process.env, os.homedir), "memory", `${agentId}.graph.sqlite`);
}

function rowToEvent(row: Record<string, unknown>): EventRecord {
  return {
    event_id: String(row.event_id),
    source_type: row.source_type === "flush_turn" ? "flush_turn" : "memory_file",
    source_ref: String(row.source_ref),
    occurred_at: String(row.occurred_at),
    entity_id: String(row.entity_id),
    actor: typeof row.actor === "string" ? row.actor : null,
    action: String(row.action),
    object: typeof row.object === "string" ? row.object : null,
    status_after: typeof row.status_after === "string" ? row.status_after : null,
    confidence: typeof row.confidence === "number" ? row.confidence : Number(row.confidence ?? 0.5),
    extractor_version: String(row.extractor_version),
    created_at: typeof row.created_at === "number" ? row.created_at : Number(row.created_at ?? 0),
  };
}

function rowToState(row: Record<string, unknown>): EntityState {
  return {
    entity_id: String(row.entity_id),
    latest_status: typeof row.latest_status === "string" ? row.latest_status : null,
    latest_owner: typeof row.latest_owner === "string" ? row.latest_owner : null,
    last_event_id: String(row.last_event_id),
    last_updated_at:
      typeof row.last_updated_at === "number"
        ? row.last_updated_at
        : Number(row.last_updated_at ?? 0),
  };
}

function quoteFtsToken(token: string): string {
  return `"${token.replaceAll('"', '""')}"`;
}

function buildFtsQuery(query: string): string {
  const tokens = query
    .split(/[^\p{L}\p{N}_-]+/u)
    .map((token) => token.trim())
    .filter(Boolean)
    .slice(0, 8);
  return tokens.map(quoteFtsToken).join(" OR ");
}

export class CanonicalStore {
  readonly dbPath: string;
  private readonly db: DatabaseSync;

  constructor(agentId: string, dbPath = graphDbPathForAgent(agentId)) {
    this.dbPath = dbPath;
    this.db = openMemoryDatabaseAtPath(dbPath, false);
    log.info(`canonical.store.open agent=${agentId} path=${dbPath}`);
    this.ensureSchema();
  }

  private ensureSchema(): void {
    this.db.exec(CANONICAL_SCHEMA_SQL);
    this.db
      .prepare("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)")
      .run("schema_version", CANONICAL_SCHEMA_VERSION);
    this.db
      .prepare("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)")
      .run("extractor_version", EXTRACTOR_VERSION);
    log.info("canonical.store.schema_ready");
  }

  close(): void {
    this.db.close();
  }

  getMeta(key: string): string | undefined {
    const row = this.db.prepare("SELECT value FROM meta WHERE key = ?").get(key) as
      | { value?: string }
      | undefined;
    return row?.value;
  }

  async upsertEvents(records: EventRecord[]): Promise<void> {
    if (records.length === 0) {
      log.info("canonical.store.upsert_events records=0");
      return;
    }
    const upsert = this.db.prepare(
      `INSERT OR REPLACE INTO event_records(
        event_id, source_type, source_ref, occurred_at, entity_id, actor, action, object,
        status_after, confidence, extractor_version, created_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    );
    const deleteFts = this.db.prepare("DELETE FROM event_fts WHERE event_id = ?");
    const insertFts = this.db.prepare(
      `INSERT INTO event_fts(event_id, entity_id, actor, action, object, status_after)
       VALUES (?, ?, ?, ?, ?, ?)`,
    );
    this.db.exec("BEGIN IMMEDIATE");
    try {
      for (const record of records) {
        const values: SQLInputValue[] = [
          record.event_id,
          record.source_type,
          record.source_ref,
          record.occurred_at,
          record.entity_id,
          record.actor,
          record.action,
          record.object,
          record.status_after,
          record.confidence,
          record.extractor_version,
          record.created_at,
        ];
        upsert.run(...values);
        deleteFts.run(record.event_id);
        insertFts.run(
          record.event_id,
          record.entity_id,
          record.actor,
          record.action,
          record.object,
          record.status_after,
        );
      }
      this.db.exec("COMMIT");
    } catch (err) {
      this.db.exec("ROLLBACK");
      throw err;
    }
    log.info(`canonical.store.upsert_events records=${records.length}`);
  }

  async refreshEntityStates(records: EventRecord[]): Promise<EntityState[]> {
    const entityIds = [...new Set(records.map((record) => record.entity_id))];
    const prevStates = new Map<string, EntityState>();
    for (const entityId of entityIds) {
      const state = await this.getEntityState(entityId);
      if (state) {
        prevStates.set(entityId, state);
      }
    }
    const states = reduce(records, prevStates);
    if (states.length === 0) {
      log.info("canonical.store.refresh_states states=0");
      return states;
    }
    const upsert = this.db.prepare(
      `INSERT OR REPLACE INTO entity_states(
        entity_id, latest_status, latest_owner, last_event_id, last_updated_at
      ) VALUES (?, ?, ?, ?, ?)`,
    );
    this.db.exec("BEGIN IMMEDIATE");
    try {
      for (const state of states) {
        upsert.run(
          state.entity_id,
          state.latest_status,
          state.latest_owner,
          state.last_event_id,
          state.last_updated_at,
        );
      }
      this.db.exec("COMMIT");
    } catch (err) {
      this.db.exec("ROLLBACK");
      throw err;
    }
    log.info(`canonical.store.refresh_states states=${states.length}`);
    return states;
  }

  async getEntityState(entityId: string): Promise<EntityState | null> {
    const row = this.db.prepare("SELECT * FROM entity_states WHERE entity_id = ?").get(entityId) as
      | Record<string, unknown>
      | undefined;
    return row ? rowToState(row) : null;
  }

  async searchEvents(query: string, limit: number): Promise<EventRow[]> {
    const ftsQuery = buildFtsQuery(query);
    if (!ftsQuery) {
      const rows = this.db
        .prepare("SELECT * FROM event_records ORDER BY occurred_at DESC, created_at DESC LIMIT ?")
        .all(Math.max(1, limit)) as Array<Record<string, unknown>>;
      return rows.map((row) => ({ ...rowToEvent(row), fts_score: 0 }));
    }
    try {
      const rows = this.db
        .prepare(
          `SELECT e.*, bm25(event_fts) AS fts_score
           FROM event_fts
           JOIN event_records e ON e.event_id = event_fts.event_id
           WHERE event_fts MATCH ?
           ORDER BY fts_score
           LIMIT ?`,
        )
        .all(ftsQuery, Math.max(1, limit)) as Array<Record<string, unknown>>;
      return rows.map((row) => ({
        ...rowToEvent(row),
        fts_score: typeof row.fts_score === "number" ? row.fts_score : Number(row.fts_score ?? 0),
      }));
    } catch (err) {
      log.warn(`canonical.search fts_failed ${String(err)}`);
      return [];
    }
  }

  getStatus() {
    const eventRow = this.db.prepare("SELECT COUNT(*) AS count FROM event_records").get() as {
      count?: number;
    };
    const entityRow = this.db.prepare("SELECT COUNT(*) AS count FROM entity_states").get() as {
      count?: number;
    };
    return {
      dbPath: this.dbPath,
      eventsTotal: eventRow.count ?? 0,
      entitiesTotal: entityRow.count ?? 0,
      schemaVersion: this.getMeta("schema_version") ?? CANONICAL_SCHEMA_VERSION,
      extractorVersion: this.getMeta("extractor_version") ?? EXTRACTOR_VERSION,
    };
  }

  async exportJsonl(): Promise<string> {
    const eventRows = this.db
      .prepare("SELECT * FROM event_records ORDER BY occurred_at, event_id")
      .all() as Array<Record<string, unknown>>;
    const stateRows = this.db
      .prepare("SELECT * FROM entity_states ORDER BY entity_id")
      .all() as Array<Record<string, unknown>>;
    return [
      ...eventRows.map((row) => JSON.stringify({ type: "event", ...rowToEvent(row) })),
      ...stateRows.map((row) => JSON.stringify({ type: "state", ...rowToState(row) })),
    ].join("\n");
  }
}

export function getCanonicalStore(agentId: string): CanonicalStore {
  const cached = stores.get(agentId);
  if (cached) {
    return cached;
  }
  const store = new CanonicalStore(agentId);
  stores.set(agentId, store);
  return store;
}

export async function closeAllCanonicalStores(): Promise<void> {
  const count = stores.size;
  for (const store of stores.values()) {
    store.close();
  }
  stores.clear();
  log.info(`canonical.store.close_all count=${count}`);
}
