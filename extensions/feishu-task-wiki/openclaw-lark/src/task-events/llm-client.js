"use strict";

const fs = require("node:fs");
const path = require("node:path");

function readEnvFile(filePath) {
  try {
    const raw = fs.readFileSync(filePath, "utf8");
    const values = {};
    for (const line of raw.split(/\r?\n/u)) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#") || !trimmed.includes("=")) {
        continue;
      }
      const separator = trimmed.indexOf("=");
      const key = trimmed.slice(0, separator).trim();
      const value = trimmed.slice(separator + 1).trim();
      if (!key) {
        continue;
      }
      values[key] = value.replace(/^['"]|['"]$/g, "");
    }
    return values;
  } catch {
    return {};
  }
}

function loadEnv() {
  const merged = { ...process.env };
  const rootEnv = readEnvFile(path.join(process.cwd(), ".env"));
  for (const [key, value] of Object.entries(rootEnv)) {
    if (!merged[key]) {
      merged[key] = value;
    }
  }
  return merged;
}

function normalizeChatCompletionsUrl(baseUrl) {
  const base = String(baseUrl ?? "").trim().replace(/\/+$/u, "");
  if (!base) {
    return "";
  }
  if (base.endsWith("/chat/completions")) {
    return base;
  }
  return `${base}/chat/completions`;
}

function parseJsonObject(text) {
  const raw = String(text ?? "").trim();
  if (!raw) {
    throw new Error("model returned empty content");
  }
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("model JSON response must be an object");
    }
    return parsed;
  } catch {
    const start = raw.indexOf("{");
    const end = raw.lastIndexOf("}");
    if (start < 0 || end <= start) {
      throw new Error("model did not return valid JSON");
    }
    const parsed = JSON.parse(raw.slice(start, end + 1));
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("model JSON response must be an object");
    }
    return parsed;
  }
}

function buildClientFromEnv() {
  const env = loadEnv();
  const apiKey = String(env.FEISHU_TASK_WIKI_API_KEY ?? env.OPENAI_API_KEY ?? "").trim();
  const baseUrl = String(env.FEISHU_TASK_WIKI_API_BASE_URL ?? env.OPENAI_API_BASE_URL ?? "").trim();
  const model = String(
    env.FEISHU_TASK_WIKI_MODEL
      ?? env.FEISHU_BUILDER_MODEL
      ?? env.VOLCENGINE_EP_ID
      ?? env.OPENAI_MODEL
      ?? "",
  ).trim();
  const timeoutMsValue = env.FEISHU_TASK_WIKI_TIMEOUT_MS;
  const timeoutSecondsValue = env.FEISHU_BUILDER_TIMEOUT_SECONDS;
  const timeoutMs = timeoutMsValue
    ? Number.parseInt(String(timeoutMsValue), 10)
    : timeoutSecondsValue
      ? Number.parseInt(String(timeoutSecondsValue), 10) * 1000
      : 120000;
  const maxTokens = Number.parseInt(
    String(env.FEISHU_TASK_WIKI_MAX_TOKENS ?? env.FEISHU_BUILDER_MAX_TOKENS ?? "1600"),
    10,
  );
  if (!apiKey || !baseUrl || !model) {
    return null;
  }
  return {
    apiKey,
    baseUrl: normalizeChatCompletionsUrl(baseUrl),
    model,
    timeoutMs: Number.isFinite(timeoutMs) ? timeoutMs : 120000,
    maxTokens: Number.isFinite(maxTokens) ? maxTokens : 1600,
  };
}

async function requestJson(params) {
  const client = buildClientFromEnv();
  if (!client) {
    throw new Error("task wiki LLM client is not configured");
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), client.timeoutMs);
  const payload = {
    model: client.model,
    temperature: params.temperature ?? 0.2,
    max_tokens: params.maxTokens ?? client.maxTokens,
    response_format: { type: "json_object" },
    messages: [
      { role: "system", content: params.systemPrompt },
      { role: "user", content: params.userPrompt },
    ],
  };
  try {
    const response = await fetch(client.baseUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${client.apiKey}`,
      },
      body: JSON.stringify(payload),
      signal: controller.signal,
    });
    const raw = await response.text();
    if (!response.ok) {
      throw new Error(`LLM HTTP ${response.status}: ${raw}`);
    }
    const parsed = JSON.parse(raw);
    const choice = Array.isArray(parsed?.choices) ? parsed.choices[0] : null;
    const message = choice?.message;
    let content = message?.content ?? "";
    if (Array.isArray(content)) {
      content = content
        .filter((item) => item && item.type === "text")
        .map((item) => String(item.text ?? ""))
        .join("");
    }
    return parseJsonObject(content);
  } catch (error) {
    const message = String(error?.message ?? error);
    if (!/json_object|response_format/u.test(message)) {
      throw error;
    }
    const fallbackPayload = {
      model: client.model,
      temperature: params.temperature ?? 0.2,
      max_tokens: params.maxTokens ?? client.maxTokens,
      messages: [
        {
          role: "system",
          content: `${params.systemPrompt}\nReturn one JSON object only. Do not use Markdown.`,
        },
        { role: "user", content: params.userPrompt },
      ],
    };
    const response = await fetch(client.baseUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${client.apiKey}`,
      },
      body: JSON.stringify(fallbackPayload),
      signal: controller.signal,
    });
    const raw = await response.text();
    if (!response.ok) {
      throw new Error(`LLM HTTP ${response.status}: ${raw}`);
    }
    const parsed = JSON.parse(raw);
    const choice = Array.isArray(parsed?.choices) ? parsed.choices[0] : null;
    return parseJsonObject(choice?.message?.content ?? "");
  } finally {
    clearTimeout(timeout);
  }
}

module.exports = {
  buildClientFromEnv,
  requestJson,
};
