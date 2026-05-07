"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.listBindingsForTask = listBindingsForTask;
exports.backfillThreadBinding = backfillThreadBinding;
exports.resolveBinding = resolveBinding;
exports.resolveOrInitializeTask = resolveOrInitializeTask;
exports.buildTaskQueueKey = buildTaskQueueKey;
exports.buildTaskSessionKey = buildTaskSessionKey;
exports.resolveTaskBindingForInbound = resolveTaskBindingForInbound;
const crypto_1 = require("node:crypto");
const fs_1 = require("node:fs");
const os_1 = require("node:os");
const path_1 = require("node:path");
const STORE_SYMBOL = Symbol.for("openclaw.feishuTaskWiki.bindingStore");
function resolveStateDir() {
    const fromEnv = process.env.OPENCLAW_STATE_DIR;
    if (typeof fromEnv === "string" && fromEnv.trim()) {
        return fromEnv.trim();
    }
    return (0, path_1.join)((0, os_1.homedir)(), ".openclaw");
}
function resolveStorePath() {
    return (0, path_1.join)(resolveStateDir(), "feishu-task-wiki", "task-bindings.json");
}
function migrateLegacyRecords(records) {
    if (!Array.isArray(records)) {
        return { tasks: [], bindings: [] };
    }
    const tasks = [];
    const bindings = [];
    const seenTaskIds = new Set();
    for (const entry of records) {
        if (!entry || typeof entry !== "object") {
            continue;
        }
        const accountId = typeof entry.accountId === "string" ? entry.accountId : "default";
        const taskId = typeof entry.taskId === "string" ? entry.taskId : null;
        if (!taskId) {
            continue;
        }
        if (!seenTaskIds.has(`${accountId}:${taskId}`)) {
            tasks.push({
                accountId,
                taskId,
                taskKey: typeof entry.taskKey === "string" ? entry.taskKey : taskId.replace(/^task:/, ""),
                taskTitle: typeof entry.taskTitle === "string" ? entry.taskTitle : "未命名任务",
                taskSummary: typeof entry.taskSummary === "string" ? entry.taskSummary : "未命名任务",
                taskKeywords: Array.isArray(entry.taskKeywords) ? entry.taskKeywords.filter((item) => typeof item === "string") : [],
                taskStatus: "active",
                createdAt: Number.isFinite(entry.createdAt) ? entry.createdAt : Date.now(),
                updatedAt: Number.isFinite(entry.updatedAt) ? entry.updatedAt : Date.now(),
            });
            seenTaskIds.add(`${accountId}:${taskId}`);
        }
        bindings.push({
            accountId,
            taskId,
            sourceType: typeof entry.sourceType === "string" ? entry.sourceType : "chat",
            sourceId: typeof entry.sourceId === "string" ? entry.sourceId : `chat:${entry.chatId ?? ""}`,
            chatId: typeof entry.chatId === "string" ? entry.chatId : null,
            threadId: typeof entry.threadId === "string" ? entry.threadId : null,
            rootId: typeof entry.rootId === "string" ? entry.rootId : null,
            bindingStatus: typeof entry.bindingStatus === "string" ? entry.bindingStatus : "active",
            createdAt: Number.isFinite(entry.createdAt) ? entry.createdAt : Date.now(),
            updatedAt: Number.isFinite(entry.updatedAt) ? entry.updatedAt : Date.now(),
        });
    }
    return { tasks, bindings };
}
function ensureStore() {
    const globalStore = globalThis;
    const existing = globalStore[STORE_SYMBOL];
    if (existing) {
        return existing;
    }
    const filePath = resolveStorePath();
    let data = { tasks: [], bindings: [] };
    try {
        if ((0, fs_1.existsSync)(filePath)) {
            const raw = (0, fs_1.readFileSync)(filePath, "utf8");
            const parsed = JSON.parse(raw);
            if (Array.isArray(parsed)) {
                data = migrateLegacyRecords(parsed);
            }
            else if (parsed && typeof parsed === "object") {
                data = {
                    tasks: Array.isArray(parsed.tasks) ? parsed.tasks.filter((entry) => entry && typeof entry === "object") : [],
                    bindings: Array.isArray(parsed.bindings) ? parsed.bindings.filter((entry) => entry && typeof entry === "object") : [],
                };
            }
        }
    }
    catch {
        data = { tasks: [], bindings: [] };
    }
    const store = { filePath, tasks: data.tasks, bindings: data.bindings };
    globalStore[STORE_SYMBOL] = store;
    return store;
}
function persistStore(store) {
    try {
        (0, fs_1.mkdirSync)((0, path_1.dirname)(store.filePath), { recursive: true });
        (0, fs_1.writeFileSync)(store.filePath, JSON.stringify({
            tasks: store.tasks,
            bindings: store.bindings,
        }, null, 2), "utf8");
    }
    catch {
        // best effort only
    }
}
function normalizeText(input) {
    return String(input ?? "")
        .replace(/[@＠][^\s]+/g, " ")
        .replace(/[【\[][^】\]]+[】\]]/g, " ")
        .replace(/\s+/g, " ")
        .replace(/[。；;]+/g, "。")
        .trim();
}
function compactSentence(input, maxChars) {
    const normalized = normalizeText(input);
    if (!normalized) {
        return "";
    }
    return normalized.length <= maxChars ? normalized : `${normalized.slice(0, maxChars).trim()}…`;
}
function firstSentence(input) {
    const normalized = normalizeText(input);
    if (!normalized) {
        return "";
    }
    const split = normalized.split(/[。！？!?]/).map((part) => part.trim()).filter(Boolean);
    return split[0] ?? normalized;
}
function keywordCandidates(text) {
    const normalized = normalizeText(text);
    const matches = normalized.match(/[\u4e00-\u9fffA-Za-z0-9_-]{2,12}/g) ?? [];
    return matches.filter((token) => !/^(这个|那个|我们|你们|他们|然后|如果|所以|已经|还是)$/.test(token));
}
function extractTaskKeywords(texts, limit = 6) {
    const counts = new Map();
    for (const text of texts) {
        for (const token of keywordCandidates(text)) {
            counts.set(token, (counts.get(token) ?? 0) + 1);
        }
    }
    return [...counts.entries()]
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "zh-Hans-CN"))
        .slice(0, limit)
        .map(([token]) => token);
}
function normalizeAsciiTaskKey(prefix, sequence) {
    return `${String(prefix).toUpperCase()}-${String(sequence)}`;
}
function normalizeCjkTaskKey(prefix, sequence) {
    return `${String(prefix)}-${String(sequence)}`;
}
function extractCanonicalTaskKey(texts) {
    for (const rawText of texts) {
        const text = normalizeText(rawText);
        if (!text) {
            continue;
        }
        const asciiMatch = text.match(/\b([A-Za-z][A-Za-z0-9]{1,31})\s*[-_]\s*(\d{1,8})\b/u);
        if (asciiMatch) {
            return normalizeAsciiTaskKey(asciiMatch[1] ?? "", asciiMatch[2] ?? "");
        }
        const cjkMatch = text.match(/([\u4e00-\u9fff]{2,24})\s*[-－_]\s*(\d{1,8})/u);
        if (cjkMatch) {
            return normalizeCjkTaskKey(cjkMatch[1] ?? "", cjkMatch[2] ?? "");
        }
    }
    return null;
}
function resolveSourceScope(params) {
    if (params.sourceType === "doc" || params.sourceType === "comment") {
        return String(params.sourceId).trim();
    }
    if (params.threadId && String(params.threadId).trim()) {
        return `thread:${String(params.threadId).trim()}`;
    }
    if (params.rootId && String(params.rootId).trim()) {
        return `thread:${String(params.rootId).trim()}`;
    }
    if (params.chatId && String(params.chatId).trim()) {
        return `chat:${String(params.chatId).trim()}`;
    }
    return `${params.sourceType}:${String(params.sourceId).trim()}`;
}
function buildTaskProfile(params) {
    const taskKey = extractCanonicalTaskKey([
        params.rootMessageText,
        ...(params.replyTexts ?? []),
        params.chatTitle ?? "",
        params.docTitle ?? "",
    ]);
    if (!taskKey) {
        return null;
    }
    const rootSentence = firstSentence(params.rootMessageText);
    const titleSource = rootSentence || params.chatTitle?.trim() || params.docTitle?.trim() || taskKey;
    const taskTitle = compactSentence(titleSource, 36) || taskKey;
    const taskSummary = compactSentence([
        params.chatTitle?.trim(),
        params.docTitle?.trim(),
        compactSentence(params.rootMessageText, 80),
        ...(params.replyTexts ?? []).slice(0, 3).map((text) => compactSentence(text, 48)),
    ]
        .filter(Boolean)
        .join(" / "), 140) || taskTitle;
    const taskKeywords = extractTaskKeywords([
        params.rootMessageText,
        ...(params.replyTexts ?? []),
        params.chatTitle ?? "",
        params.docTitle ?? "",
    ]);
    return {
        taskId: `task:${taskKey}`,
        taskKey,
        taskTitle,
        taskSummary,
        taskKeywords,
    };
}
function buildCanonicalTaskRecord(params) {
    const profile = buildTaskProfile(params);
    if (!profile) {
        return null;
    }
    const now = Date.now();
    return {
        accountId: params.accountId,
        ...profile,
        taskStatus: "active",
        createdAt: now,
        updatedAt: now,
    };
}
function buildTaskSourceBindingRecord(params, taskId) {
    const now = Date.now();
    return {
        accountId: params.accountId,
        taskId,
        sourceType: params.sourceType,
        sourceId: String(params.sourceId).trim(),
        chatId: params.chatId?.trim() || null,
        threadId: params.threadId?.trim() || null,
        rootId: params.rootId?.trim() || null,
        bindingStatus: "active",
        createdAt: now,
        updatedAt: now,
    };
}
function findTaskById(tasks, accountId, taskId) {
    return tasks.find((task) => task.accountId === accountId && task.taskId === taskId && task.taskStatus === "active") ?? null;
}
function findTaskByKey(tasks, accountId, taskKey) {
    return tasks.find((task) => task.accountId === accountId && task.taskKey === taskKey && task.taskStatus === "active") ?? null;
}
function mergeTaskKeywords(primary, secondary) {
    const merged = new Set();
    for (const keyword of [...primary, ...secondary]) {
        const normalized = String(keyword ?? "").trim();
        if (normalized) {
            merged.add(normalized);
        }
    }
    return [...merged].slice(0, 8);
}
function mergeTaskProfile(existing, incoming) {
    if (!incoming) {
        return existing;
    }
    return {
        ...existing,
        taskTitle: existing.taskTitle || incoming.taskTitle,
        taskSummary: existing.taskSummary || incoming.taskSummary,
        taskKeywords: mergeTaskKeywords(existing.taskKeywords ?? [], incoming.taskKeywords ?? []),
    };
}
function resolveTaskForBinding(tasks, binding) {
    return findTaskById(tasks, binding.accountId, binding.taskId);
}
function resolveBinding(params) {
    const store = ensureStore();
    const activeBindings = store.bindings.filter((binding) => binding.accountId === params.accountId && binding.bindingStatus === "active");
    const threadId = params.threadId?.trim();
    if (threadId) {
        const binding = activeBindings.find((entry) => entry.threadId === threadId);
        if (binding) {
            const task = resolveTaskForBinding(store.tasks, binding);
            if (task) {
                return { task, binding, reason: "thread_id" };
            }
        }
    }
    const rootId = params.rootId?.trim();
    if (rootId) {
        const binding = activeBindings.find((entry) => entry.rootId === rootId);
        if (binding) {
            const task = resolveTaskForBinding(store.tasks, binding);
            if (task) {
                return { task, binding, reason: "root_id" };
            }
        }
    }
    const sourceId = params.sourceId?.trim();
    if (sourceId && params.sourceType) {
        const binding = activeBindings.find((entry) => entry.sourceType === params.sourceType && entry.sourceId === sourceId);
        if (binding) {
            const task = resolveTaskForBinding(store.tasks, binding);
            if (task) {
                return { task, binding, reason: "source_id" };
            }
        }
    }
    const chatId = params.chatId?.trim();
    if (chatId) {
        const chatBindings = activeBindings.filter((entry) => entry.chatId === chatId);
        if (chatBindings.length > 0 && params.taskKey?.trim()) {
            const semantic = chatBindings.find((entry) => {
                const task = resolveTaskForBinding(store.tasks, entry);
                return task?.taskKey === params.taskKey;
            });
            if (semantic) {
                const task = resolveTaskForBinding(store.tasks, semantic);
                if (task) {
                    return { task, binding: semantic, reason: "task_key" };
                }
            }
        }
        if (chatBindings.length > 1) {
            const taskIds = new Set(chatBindings.map((entry) => entry.taskId));
            if (taskIds.size === 1) {
                const preferred = chatBindings.find((entry) => !entry.threadId && !entry.rootId) ?? chatBindings[0];
                const task = resolveTaskForBinding(store.tasks, preferred);
                if (task) {
                    return { task, binding: preferred, reason: "chat_id" };
                }
            }
        }
        if (chatBindings.length === 1) {
            const task = resolveTaskForBinding(store.tasks, chatBindings[0]);
            if (task) {
                return { task, binding: chatBindings[0], reason: "chat_id" };
            }
        }
    }
    return null;
}
function needsThreadBackfill(binding, params) {
    if (binding.threadId || binding.rootId) {
        return null;
    }
    if (params.threadId?.trim()) {
        return "thread_backfill";
    }
    if (params.rootId?.trim()) {
        return "root_backfill";
    }
    return null;
}
function resolveExactSourceBinding(store, params) {
    const activeBindings = store.bindings.filter((binding) => binding.accountId === params.accountId && binding.bindingStatus === "active");
    const threadId = params.threadId?.trim();
    if (threadId) {
        const binding = activeBindings.find((entry) => entry.threadId === threadId);
        if (binding) {
            const task = resolveTaskForBinding(store.tasks, binding);
            if (task) {
                return { task, binding, reason: "thread_id" };
            }
        }
    }
    const rootId = params.rootId?.trim();
    if (rootId) {
        const binding = activeBindings.find((entry) => entry.rootId === rootId);
        if (binding) {
            const task = resolveTaskForBinding(store.tasks, binding);
            if (task) {
                return { task, binding, reason: "root_id" };
            }
        }
    }
    const sourceId = params.sourceId?.trim();
    if (sourceId && params.sourceType) {
        const binding = activeBindings.find((entry) => entry.sourceType === params.sourceType && entry.sourceId === sourceId);
        if (binding) {
            const task = resolveTaskForBinding(store.tasks, binding);
            if (task) {
                return { task, binding, reason: "source_id" };
            }
        }
    }
    return null;
}
function backfillThreadBinding(params) {
    const store = ensureStore();
    const existing = resolveExactSourceBinding(store, {
        accountId: params.accountId,
        sourceType: "thread",
        sourceId: params.sourceId,
        chatId: params.chatId,
        threadId: params.threadId,
        rootId: params.rootId,
    });
    if (existing) {
        return existing;
    }
    const binding = buildTaskSourceBindingRecord(params, params.task.taskId);
    store.bindings.push(binding);
    persistStore(store);
    return {
        task: params.task,
        binding,
        reason: params.threadId?.trim() ? "thread_backfill" : "root_backfill",
    };
}
function resolveOrInitializeTask(params) {
    const store = ensureStore();
    const profile = buildTaskProfile(params);
    const existing = resolveBinding({
        accountId: params.accountId,
        sourceType: params.sourceType,
        sourceId: params.sourceId,
        chatId: params.chatId,
        threadId: params.threadId,
        rootId: params.rootId,
        taskKey: profile?.taskKey ?? null,
    });
    if (existing) {
        const backfilledReason = needsThreadBackfill(existing.binding, params);
        if (backfilledReason) {
            return backfillThreadBinding({
                ...params,
                task: existing.task,
            });
        }
        return existing;
    }
    if (!params.allowInitialize || !params.rootMessageText?.trim()) {
        return null;
    }
    if (!params.threadId && !params.rootId && !params.chatId) {
        return null;
    }
    if (!profile) {
        return null;
    }
    const existingTask = findTaskByKey(store.tasks, params.accountId, profile.taskKey);
    if (existingTask) {
        Object.assign(existingTask, {
            ...mergeTaskProfile(existingTask, profile),
            updatedAt: Date.now(),
        });
        const binding = buildTaskSourceBindingRecord(params, existingTask.taskId);
        store.bindings.push(binding);
        persistStore(store);
        return {
            task: existingTask,
            binding,
            reason: "task_key",
        };
    }
    const task = buildCanonicalTaskRecord(params);
    if (!task) {
        return null;
    }
    store.tasks.push(task);
    const binding = buildTaskSourceBindingRecord(params, task.taskId);
    store.bindings.push(binding);
    persistStore(store);
    return {
        task,
        binding,
        reason: "initialized",
    };
}
function listBindingsForTask(taskId, accountId) {
    const store = ensureStore();
    return store.bindings.filter((binding) => binding.taskId === taskId
        && binding.bindingStatus === "active"
        && (typeof accountId !== "string" || binding.accountId === accountId));
}
function buildTaskSessionKey(params) {
    return `agent:${params.agentId}:feishu-task:${params.taskId}:${params.sourceScope}`;
}
function buildTaskQueueKey(params) {
    return `${params.accountId}:task:${params.taskId}:${params.sourceScope}`;
}
function resolveTaskBindingForInbound(params) {
    const resolved = resolveOrInitializeTask(params);
    if (!resolved) {
        return null;
    }
    const sourceScope = resolveSourceScope(resolved.binding);
    return {
        task: resolved.task,
        binding: resolved.binding,
        reason: resolved.reason,
        sourceScope,
        taskSessionKey: typeof params.agentId === "string" && params.agentId.trim()
            ? buildTaskSessionKey({
                agentId: params.agentId,
                taskId: resolved.task.taskId,
                sourceScope,
            })
            : null,
        taskQueueKey: buildTaskQueueKey({
            accountId: params.accountId,
            taskId: resolved.task.taskId,
            sourceScope,
        }),
    };
}
