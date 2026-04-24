#!/usr/bin/env python3
"""
dump-graph-index.py — 查看 memory-core graph index SQLite 数据库内容
用法: python3 dump-graph-index.py [数据库路径]
默认路径: ~/.openclaw/memory/main.graph.sqlite
"""

import sqlite3
import json
import sys
import os
from datetime import datetime, timezone

DB_PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/.openclaw/memory/main.graph.sqlite")

def ts(ms):
    if ms is None:
        return "—"
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return str(ms)

def jpp(s, indent=2):
    try:
        return json.dumps(json.loads(s), ensure_ascii=False, indent=indent)
    except Exception:
        return s

def hr(title=""):
    print(f"\n{'='*60}")
    if title:
        print(f"  {title}")
        print(f"{'='*60}")

def count(cur, table):
    try:
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        return cur.fetchone()[0]
    except Exception:
        return "N/A"

if not os.path.exists(DB_PATH):
    print(f"数据库不存在: {DB_PATH}")
    sys.exit(1)

con = sqlite3.connect(DB_PATH)
con.row_factory = sqlite3.Row
cur = con.cursor()

# ── 概览 ──────────────────────────────────────────────────────────────
hr("数据库概览")
print(f"路径: {DB_PATH}")
print(f"大小: {os.path.getsize(DB_PATH) / 1024:.1f} KB\n")

tables = [
    "meta", "graph_metrics",
    "evidence_records", "event_type_registry", "event_records_v2",
    "graph_entities_v2", "graph_edges_v2",
    "workflow_state_view_v2",
    "source_projection_state", "projection_inbox",
    "recent_graph_hits",
]
for t in tables:
    n = count(cur, t)
    print(f"  {t:<35} {n} 行")

# ── meta ──────────────────────────────────────────────────────────────
hr("meta — 数据库元信息")
for row in cur.execute("SELECT key, value FROM meta ORDER BY key"):
    print(f"  {row['key']}: {row['value']}")

# ── graph_metrics ─────────────────────────────────────────────────────
hr("graph_metrics — 运行统计")
for row in cur.execute("SELECT key, value FROM graph_metrics ORDER BY key"):
    print(f"  {row['key']}: {row['value']}")

# ── event_type_registry ───────────────────────────────────────────────
hr("event_type_registry — 已注册事件类型")
for row in cur.execute("SELECT event_type, subject_type, object_type, description, enabled FROM event_type_registry ORDER BY event_type"):
    status = "✓" if row["enabled"] else "✗"
    obj = f" → {row['object_type']}" if row["object_type"] else ""
    print(f"  [{status}] {row['event_type']:<35} {row['subject_type']}{obj}")
    if row["description"]:
        print(f"       {row['description']}")

# ── graph_entities_v2 ─────────────────────────────────────────────────
hr("graph_entities_v2 — 实体节点")
rows = list(cur.execute(
    "SELECT entity_ref, entity_type, canonical_name, alias_json, first_seen_at, last_seen_at FROM graph_entities_v2 ORDER BY last_seen_at DESC LIMIT 50"
))
if not rows:
    print("  （空）")
for row in rows:
    aliases = json.loads(row["alias_json"] or "[]")
    alias_str = f"  别名: {aliases}" if aliases else ""
    print(f"  [{row['entity_type']}] {row['canonical_name']}")
    print(f"    ref: {row['entity_ref']}")
    print(f"    首见: {row['first_seen_at']}  最近: {row['last_seen_at']}{alias_str}")

# ── graph_edges_v2 ────────────────────────────────────────────────────
hr("graph_edges_v2 — 实体关系边")
rows = list(cur.execute(
    "SELECT src_ref, edge_type, dst_ref, active, valid_from, valid_to FROM graph_edges_v2 ORDER BY valid_from DESC LIMIT 50"
))
if not rows:
    print("  （空）")
for row in rows:
    active = "✓" if row["active"] else "✗"
    valid_to = f" → {row['valid_to']}" if row["valid_to"] else " → 至今"
    print(f"  [{active}] {row['src_ref']}  --{row['edge_type']}-->  {row['dst_ref']}")
    print(f"       有效期: {row['valid_from']}{valid_to}")

# ── event_records_v2 ──────────────────────────────────────────────────
hr("event_records_v2 — 提取的事件（最近 30 条）")
rows = list(cur.execute(
    "SELECT event_id, event_type, subject_ref, actor_ref, object_ref, occurred_at, confidence, payload_json FROM event_records_v2 ORDER BY occurred_at DESC LIMIT 30"
))
if not rows:
    print("  （空）")
for row in rows:
    actor = f"  actor: {row['actor_ref']}" if row["actor_ref"] else ""
    obj = f"  object: {row['object_ref']}" if row["object_ref"] else ""
    payload = json.loads(row["payload_json"] or "{}")
    print(f"  {row['event_type']}")
    print(f"    subject: {row['subject_ref']}{actor}{obj}")
    print(f"    时间: {row['occurred_at']}  置信度: {row['confidence']:.2f}")
    if payload:
        print(f"    payload: {json.dumps(payload, ensure_ascii=False)}")

# ── evidence_records ──────────────────────────────────────────────────
hr("evidence_records — 原始证据（最近 20 条）")
rows = list(cur.execute(
    "SELECT evidence_id, source_platform, source_kind, session_key, chat_id, occurred_at, content_text FROM evidence_records ORDER BY created_at DESC LIMIT 20"
))
if not rows:
    print("  （空）")
for row in rows:
    text = (row["content_text"] or "")[:120].replace("\n", " ")
    print(f"  [{row['source_platform']}/{row['source_kind']}] session={row['session_key']}  chat={row['chat_id']}")
    print(f"    时间: {row['occurred_at']}")
    if text:
        print(f"    内容: {text}")

# ── workflow_state_view_v2 ────────────────────────────────────────────
hr("workflow_state_view_v2 — 任务/工作流状态")
rows = list(cur.execute(
    "SELECT task_ref, current_owner_ref, current_stage, approval_status, current_blocker_ref, last_event_time, next_action_json FROM workflow_state_view_v2 ORDER BY updated_at DESC LIMIT 30"
))
if not rows:
    print("  （空）")
for row in rows:
    owner = f"  负责人: {row['current_owner_ref']}" if row["current_owner_ref"] else ""
    stage = f"  阶段: {row['current_stage']}" if row["current_stage"] else ""
    approval = f"  审批: {row['approval_status']}" if row["approval_status"] else ""
    blocker = f"  阻塞: {row['current_blocker_ref']}" if row["current_blocker_ref"] else ""
    next_action = json.loads(row["next_action_json"] or "{}")
    print(f"  {row['task_ref']}")
    print(f"    最后更新: {row['last_event_time']}{owner}{stage}{approval}{blocker}")
    if next_action:
        print(f"    下一步: {json.dumps(next_action, ensure_ascii=False)}")

# ── source_projection_state ───────────────────────────────────────────
hr("source_projection_state — Projection 进度")
rows = list(cur.execute("SELECT * FROM source_projection_state ORDER BY last_projected_at DESC"))
if not rows:
    print("  （空）")
for row in rows:
    print(f"  [{row['status']}] {row['source_kind']}:{row['source_id']}")
    print(f"    已处理到: {row['covered_until_entry_id']}  版本: {row['projection_version']}")
    print(f"    上次 projection: {ts(row['last_projected_at'])}")

# ── projection_inbox ──────────────────────────────────────────────────
hr("projection_inbox — 待处理队列（未 drain 的）")
rows = list(cur.execute(
    "SELECT id, source_kind, source_id, first_entry_id, last_entry_id, dirty_reason, signal_strength, strong_event, created_at, drained_at FROM projection_inbox WHERE drained_at IS NULL ORDER BY created_at DESC LIMIT 20"
))
if not rows:
    print("  （无待处理任务）")
for row in rows:
    strong = " [强信号]" if row["strong_event"] else ""
    print(f"  #{row['id']} {row['source_kind']}:{row['source_id']}{strong}")
    print(f"    原因: {row['dirty_reason']}  信号强度: {row['signal_strength']}")
    print(f"    entry 范围: {row['first_entry_id']} ~ {row['last_entry_id']}")
    print(f"    入队: {ts(row['created_at'])}")

# ── recent_graph_hits ─────────────────────────────────────────────────
hr("recent_graph_hits — 最近图谱命中缓存（最近 20 条）")
rows = list(cur.execute(
    "SELECT session_key, source_ref, hit_type, entity_id, query, last_returned_at, used_at FROM recent_graph_hits ORDER BY last_returned_at DESC LIMIT 20"
))
if not rows:
    print("  （空）")
for row in rows:
    used = f"  已使用: {ts(row['used_at'])}" if row["used_at"] else "  未使用"
    query = f"  查询: {row['query']}" if row["query"] else ""
    print(f"  [{row['hit_type']}] {row['source_ref']}")
    print(f"    entity: {row['entity_id']}  session: {row['session_key']}")
    print(f"    最近返回: {ts(row['last_returned_at'])}{used}{query}")

con.close()
print(f"\n{'='*60}")
print("完成")
