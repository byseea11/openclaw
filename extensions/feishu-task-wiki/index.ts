import {
  defineBundledChannelEntry,
  loadBundledEntryExportSync,
} from "openclaw/plugin-sdk/channel-entry-contract";
import type { OpenClawPluginApi } from "openclaw/plugin-sdk/channel-entry-contract";

export * from "./api.ts";

function registerFeishuTaskWikiFull(api: OpenClawPluginApi) {
  const register = loadBundledEntryExportSync<(api: OpenClawPluginApi) => void>(import.meta.url, {
    specifier: "./api.ts",
    exportName: "registerFeishuTaskWikiFull",
  });
  register(api);
}

export default defineBundledChannelEntry({
  id: "feishu-task-wiki",
  name: "Feishu Task Wiki",
  description: "Feishu/Lark channel with task-first runtime session routing",
  importMetaUrl: import.meta.url,
  plugin: {
    specifier: "./api.ts",
    exportName: "feishuTaskWikiChannelPlugin",
  },
  registerFull(api) {
    registerFeishuTaskWikiFull(api);
  },
});
