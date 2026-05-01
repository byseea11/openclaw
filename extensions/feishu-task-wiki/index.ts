import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";

export * from "./api.ts";

export default definePluginEntry({
  id: "feishu-task-wiki",
  name: "Feishu Task Wiki",
  description: "Task-first routing helpers for Feishu collaboration memory",
  register() {},
});
