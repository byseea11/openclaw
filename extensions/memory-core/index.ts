import { formatErrorMessage } from "openclaw/plugin-sdk/error-runtime";
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
import {
  handleGraphFlushResult,
  handleGraphAfterTurn,
  handleGraphBeforeCompaction,
  noteGraphUsageFromAssistantOutput,
  noteGraphUsageFromMemoryGet,
} from "./src/canonical/index.js";
import { registerMemoryCli } from "./src/cli.js";
import { registerDreamingCommand } from "./src/dreaming-command.js";
import { registerShortTermPromotionDreaming } from "./src/dreaming.js";
import {
  buildMemoryFlushPlan,
  DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES,
  DEFAULT_MEMORY_FLUSH_PROMPT,
  DEFAULT_MEMORY_FLUSH_SOFT_TOKENS,
} from "./src/flush-plan.js";
import { registerBuiltInMemoryEmbeddingProviders } from "./src/memory/provider-adapters.js";
import { buildPromptSection } from "./src/prompt-section.js";
import { listMemoryCorePublicArtifacts } from "./src/public-artifacts.js";
import { memoryRuntime } from "./src/runtime-provider.js";
import { createMemoryGetTool, createMemorySearchTool } from "./src/tools.js";
export {
  buildMemoryFlushPlan,
  DEFAULT_MEMORY_FLUSH_FORCE_TRANSCRIPT_BYTES,
  DEFAULT_MEMORY_FLUSH_PROMPT,
  DEFAULT_MEMORY_FLUSH_SOFT_TOKENS,
} from "./src/flush-plan.js";
export { buildPromptSection } from "./src/prompt-section.js";

export default definePluginEntry({
  id: "memory-core",
  name: "Memory (Core)",
  description: "File-backed memory search tools and CLI",
  kind: "memory",
  register(api) {
    registerBuiltInMemoryEmbeddingProviders(api);
    registerShortTermPromotionDreaming(api);
    registerDreamingCommand(api);
    api.registerMemoryCapability({
      promptBuilder: buildPromptSection,
      flushPlanResolver: buildMemoryFlushPlan,
      flushResultHandler: handleGraphFlushResult,
      afterTurnObserver: handleGraphAfterTurn,
      beforeCompactionObserver: handleGraphBeforeCompaction,
      runtime: memoryRuntime,
      publicArtifacts: {
        listArtifacts: listMemoryCorePublicArtifacts,
      },
    });

    api.registerTool(
      (ctx) =>
        createMemorySearchTool({
          config: ctx.config,
          agentSessionKey: ctx.sessionKey,
        }),
      { names: ["memory_search"] },
    );

    api.registerTool(
      (ctx) =>
        createMemoryGetTool({
          config: ctx.config,
          agentSessionKey: ctx.sessionKey,
        }),
      { names: ["memory_get"] },
    );

    api.on("after_tool_call", async (event, ctx) => {
      try {
        if (event.toolName !== "memory_get" || !ctx.agentId || !ctx.sessionKey) {
          return;
        }
        const params =
          event.params && typeof event.params === "object"
            ? (event.params as Record<string, unknown>)
            : null;
        if (typeof params?.path !== "string" || !params.path.trim()) {
          return;
        }
        await noteGraphUsageFromMemoryGet({
          cfg: api.config,
          agentId: ctx.agentId,
          sessionKey: ctx.sessionKey,
          path: params.path,
          from: typeof params.from === "number" ? params.from : undefined,
          lines: typeof params.lines === "number" ? params.lines : undefined,
        });
      } catch (err) {
        api.logger.warn(
          `memory-core: graph usage after_tool_call failed: ${formatErrorMessage(err)}`,
        );
      }
    });

    api.on("llm_output", async (event, ctx) => {
      try {
        if (!ctx.agentId || !ctx.sessionKey || event.assistantTexts.length === 0) {
          return;
        }
        await noteGraphUsageFromAssistantOutput({
          cfg: api.config,
          agentId: ctx.agentId,
          sessionKey: ctx.sessionKey,
          assistantTexts: event.assistantTexts,
        });
      } catch (err) {
        api.logger.warn(`memory-core: graph usage llm_output failed: ${formatErrorMessage(err)}`);
      }
    });

    api.registerCli(
      ({ program }) => {
        registerMemoryCli(program);
      },
      {
        descriptors: [
          {
            name: "memory",
            description: "Search, inspect, and reindex memory files",
            hasSubcommands: true,
          },
        ],
      },
    );
  },
});
