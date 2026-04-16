import { createSubsystemLogger } from "openclaw/plugin-sdk/memory-core-host-engine-foundation";
import type { RawEvent } from "./schema.js";

const log = createSubsystemLogger("memory");

export type LLMClient = unknown;

function isRawEvent(value: unknown): value is RawEvent {
  const record = value && typeof value === "object" ? (value as Record<string, unknown>) : null;
  return (
    typeof record?.action === "string" &&
    record.action.trim().length > 0 &&
    typeof record.source_ref === "string" &&
    record.source_ref.trim().length > 0
  );
}

export async function extract(
  text: string,
  sourceRef: string,
  _llmClient?: LLMClient,
): Promise<RawEvent[]> {
  log.info(`canonical.extract.stub_called source_ref=${sourceRef} chars=${text.length}`);
  return [];
}

export function parseGraphJsonBlock(outputText: string): RawEvent[] {
  const blocks = [...outputText.matchAll(/```json\s*([\s\S]*?)```/gi)].map(
    (match) => match[1] ?? "",
  );
  const candidates = blocks.length > 0 ? blocks.toReversed() : [outputText];
  for (const candidate of candidates) {
    try {
      const parsed = JSON.parse(candidate.trim()) as { events?: unknown };
      const rawEvents = Array.isArray(parsed.events) ? parsed.events.filter(isRawEvent) : [];
      log.info(`canonical.extract.parse_ok events=${rawEvents.length}`);
      return rawEvents;
    } catch {
      // Try the next JSON block. The final warning below preserves the non-throwing contract.
    }
  }
  log.warn("canonical.extract.parse_failed events=0");
  return [];
}
