import fs from "node:fs/promises";
import path from "node:path";
import type { OpenClawConfig } from "openclaw/plugin-sdk/core";
import { createSubsystemLogger } from "openclaw/plugin-sdk/memory-core-host-engine-foundation";
import { canonicalize } from "./canonicalizer.js";
import { extract } from "./extractor.js";
import { EXTRACTOR_VERSION, type EventRecord } from "./schema.js";
import { getCanonicalStore } from "./store.js";

const log = createSubsystemLogger("memory");
const DAILY_MEMORY_FILE_RE = /^\d{4}-\d{2}-\d{2}\.md$/;

export type BootstrapCanonicalIndexResult = {
  filesScanned: number;
  eventsExtracted: number;
  recordsWritten: number;
};

async function fileExists(filePath: string): Promise<boolean> {
  try {
    const stat = await fs.stat(filePath);
    return stat.isFile();
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") {
      return false;
    }
    throw err;
  }
}

async function listBootstrapFiles(workspaceDir: string): Promise<string[]> {
  const files: string[] = [];
  const rootMemory = path.join(workspaceDir, "MEMORY.md");
  if (await fileExists(rootMemory)) {
    files.push(rootMemory);
  }
  const memoryDir = path.join(workspaceDir, "memory");
  try {
    const entries = await fs.readdir(memoryDir, { withFileTypes: true });
    for (const entry of entries) {
      if (!entry.isFile() || !DAILY_MEMORY_FILE_RE.test(entry.name)) {
        continue;
      }
      files.push(path.join(memoryDir, entry.name));
    }
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code !== "ENOENT") {
      throw err;
    }
  }
  return files.toSorted((left, right) => left.localeCompare(right));
}

function sourceRefForFile(workspaceDir: string, filePath: string, lineCount: number): string {
  const relPath = path.relative(workspaceDir, filePath).replaceAll("\\", "/");
  return `${relPath}#L1-L${Math.max(1, lineCount)}`;
}

export async function bootstrapCanonicalIndex(params: {
  cfg?: OpenClawConfig;
  agentId: string;
  workspaceDir: string;
  force?: boolean;
  progress?: (update: { completed: number; total: number; label?: string }) => void;
}): Promise<BootstrapCanonicalIndexResult> {
  const files = await listBootstrapFiles(params.workspaceDir);
  log.info(
    `canonical.bootstrap.start agent=${params.agentId} files=${files.length} force=${Boolean(params.force)}`,
  );
  const store = getCanonicalStore(params.agentId);
  const records: EventRecord[] = [];
  let eventsExtracted = 0;
  for (const [index, filePath] of files.entries()) {
    const text = await fs.readFile(filePath, "utf-8");
    const lineCount = text.split(/\r?\n/).length;
    const sourceRef = sourceRefForFile(params.workspaceDir, filePath, lineCount);
    log.info(`canonical.bootstrap.file source_ref=${sourceRef}`);
    const raw = await extract(text, sourceRef);
    eventsExtracted += raw.length;
    records.push(...canonicalize(raw, EXTRACTOR_VERSION));
    params.progress?.({
      completed: index + 1,
      total: files.length,
      label: `Graph bootstrap ${path.basename(filePath)}`,
    });
  }
  await store.upsertEvents(records);
  await store.refreshEntityStates(records);
  log.info(
    `canonical.bootstrap.done files=${files.length} events=${eventsExtracted} records=${records.length}`,
  );
  return {
    filesScanned: files.length,
    eventsExtracted,
    recordsWritten: records.length,
  };
}
