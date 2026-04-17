import fs from "node:fs/promises";
import path from "node:path";
import { extract } from "../extensions/memory-core/src/canonical/extractor.js";

function toSourceRef(filePath: string): string {
  const normalized = filePath.replaceAll("\\", "/");
  return normalized.includes("#L") ? normalized : `${normalized}#L1-L1`;
}

async function main() {
  const files = process.argv.slice(2);
  if (files.length === 0) {
    throw new Error("Usage: bun scripts/memory-graph-dryrun.ts <file...>");
  }
  const reports = [];
  for (const file of files) {
    const absolute = path.resolve(file);
    const text = await fs.readFile(absolute, "utf8");
    const relative = path.relative(process.cwd(), absolute).replaceAll("\\", "/");
    const events = await extract(text, toSourceRef(relative));
    const actionCounts = Object.entries(
      events.reduce<Record<string, number>>((acc, event) => {
        acc[event.action] = (acc[event.action] ?? 0) + 1;
        return acc;
      }, {}),
    )
      .map(([action, count]) => `- ${action}: ${count}`)
      .join("\n");
    const occurredCount = events.filter((event) => typeof event.occurred_at === "string").length;
    const preciseRefs = events.filter((event) => /#L\d+(?:-L?\d+)?$/.test(event.source_ref)).length;
    reports.push(
      [
        `## ${relative}`,
        "",
        `- events: ${events.length}`,
        `- occurred_at coverage: ${occurredCount}/${events.length}`,
        `- precise source_ref coverage: ${preciseRefs}/${events.length}`,
        "",
        "### action distribution",
        actionCounts || "- (none)",
        "",
        "### raw events",
        "```json",
        JSON.stringify(events, null, 2),
        "```",
      ].join("\n"),
    );
  }
  process.stdout.write(`# Memory Graph Dry Run\n\n${reports.join("\n\n")}\n`);
}

await main();
