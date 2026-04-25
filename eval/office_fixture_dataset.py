"""Deterministic realistic office snapshot fixtures for OpenClaw evals."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from eval.office_dataset import (
    EMPLOYEES_CSV,
    EMPLOYEES_JSON,
    OFFICE_EVENTS_JSONL,
    SNAPSHOT_LOCK,
    SNAPSHOT_METADATA_JSON,
    VALIDATION_MANIFEST_JSON,
    export_employees_csv,
    normalize_employee,
    normalize_office_event,
    normalize_validation_case,
)
from eval.scorers.common import dump_json, dump_jsonl

ACME_Q2_OPS_SNAPSHOT_ID = "acme_q2_ops_v1"
ACME_WORKSPACE_ID = "feishu_test_workspace_acme_q2_ops"


def _employee(
    employee_id: str,
    open_id: str,
    name: str,
    department_id: str,
    department_name: str,
    title: str,
    manager_id: str = "",
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    return normalize_employee(
        {
            "employee_id": employee_id,
            "open_id": open_id,
            "name": name,
            "department_id": department_id,
            "department_name": department_name,
            "title": title,
            "manager_id": manager_id,
            "employment_status": "active",
            "aliases": aliases or [],
        }
    )


EMPLOYEES: list[dict[str, Any]] = [
    _employee("emp-acme-001", "ou_acme_ceo", "Elena Park", "dept-exec", "Executive", "CEO", aliases=["elena", "CEO"]),
    _employee(
        "emp-acme-002",
        "ou_acme_cpo",
        "Maya Singh",
        "dept-product",
        "Product",
        "Chief Product Officer",
        "ou_acme_ceo",
        ["maya", "CPO"],
    ),
    _employee(
        "emp-acme-003",
        "ou_acme_product_pm",
        "Alice Chen",
        "dept-product",
        "Product",
        "Senior Product Manager",
        "ou_acme_cpo",
        ["alice", "launch PM"],
    ),
    _employee(
        "emp-acme-004",
        "ou_acme_design",
        "Leo Martinez",
        "dept-product",
        "Product",
        "Product Designer",
        "ou_acme_cpo",
        ["leo", "design"],
    ),
    _employee(
        "emp-acme-005",
        "ou_acme_cto",
        "Nora Williams",
        "dept-engineering",
        "Engineering",
        "Chief Technology Officer",
        "ou_acme_ceo",
        ["nora", "CTO"],
    ),
    _employee(
        "emp-acme-006",
        "ou_acme_eng_mgr",
        "Ben Carter",
        "dept-engineering",
        "Engineering",
        "Engineering Manager",
        "ou_acme_cto",
        ["ben", "eng manager"],
    ),
    _employee(
        "emp-acme-007",
        "ou_acme_backend",
        "Priya Raman",
        "dept-engineering",
        "Engineering",
        "Backend Engineer",
        "ou_acme_eng_mgr",
        ["priya", "backend"],
    ),
    _employee(
        "emp-acme-008",
        "ou_acme_frontend",
        "Owen Brooks",
        "dept-engineering",
        "Engineering",
        "Frontend Engineer",
        "ou_acme_eng_mgr",
        ["owen", "frontend"],
    ),
    _employee(
        "emp-acme-009",
        "ou_acme_platform_mgr",
        "Samir Patel",
        "dept-platform",
        "Platform",
        "Platform Lead",
        "ou_acme_cto",
        ["samir", "platform"],
    ),
    _employee(
        "emp-acme-010",
        "ou_acme_sre",
        "Iris Kim",
        "dept-platform",
        "Platform",
        "SRE",
        "ou_acme_platform_mgr",
        ["iris", "sre"],
    ),
    _employee(
        "emp-acme-011",
        "ou_acme_security_lead",
        "Grace Liu",
        "dept-security",
        "Security",
        "Security Lead",
        "ou_acme_cto",
        ["grace", "security"],
    ),
    _employee(
        "emp-acme-012",
        "ou_acme_seceng",
        "Noah Evans",
        "dept-security",
        "Security",
        "Security Engineer",
        "ou_acme_security_lead",
        ["noah", "seceng"],
    ),
    _employee(
        "emp-acme-013",
        "ou_acme_data_lead",
        "Hannah Zhao",
        "dept-data",
        "Data",
        "Data Lead",
        "ou_acme_cto",
        ["hannah", "data"],
    ),
    _employee(
        "emp-acme-014",
        "ou_acme_data_eng",
        "Victor Huang",
        "dept-data",
        "Data",
        "Data Engineer",
        "ou_acme_data_lead",
        ["victor", "data eng"],
    ),
    _employee(
        "emp-acme-015",
        "ou_acme_ops_head",
        "Rachel Adams",
        "dept-operations",
        "Operations",
        "Operations Director",
        "ou_acme_ceo",
        ["rachel", "ops"],
    ),
    _employee(
        "emp-acme-016",
        "ou_acme_release",
        "Tom Nguyen",
        "dept-operations",
        "Operations",
        "Release Manager",
        "ou_acme_ops_head",
        ["tom", "release"],
    ),
    _employee(
        "emp-acme-017",
        "ou_acme_cfo",
        "Claire Dubois",
        "dept-finance",
        "Finance",
        "Chief Financial Officer",
        "ou_acme_ceo",
        ["claire", "CFO"],
    ),
    _employee(
        "emp-acme-018",
        "ou_acme_finance_ops",
        "Mateo Rossi",
        "dept-finance",
        "Finance",
        "Finance Operations Manager",
        "ou_acme_cfo",
        ["mateo", "finance ops"],
    ),
    _employee(
        "emp-acme-019",
        "ou_acme_legal",
        "Ava Johnson",
        "dept-legal",
        "Legal",
        "Legal Counsel",
        "ou_acme_ceo",
        ["ava", "legal"],
    ),
    _employee(
        "emp-acme-020",
        "ou_acme_marketing",
        "Zoe Miller",
        "dept-marketing",
        "Marketing",
        "Marketing Lead",
        "ou_acme_cpo",
        ["zoe", "marketing"],
    ),
    _employee(
        "emp-acme-021",
        "ou_acme_cs_lead",
        "Daniel Smith",
        "dept-customer-success",
        "Customer Success",
        "Customer Success Lead",
        "ou_acme_ceo",
        ["daniel", "CS"],
    ),
    _employee(
        "emp-acme-022",
        "ou_acme_support",
        "Sofia Garcia",
        "dept-customer-success",
        "Customer Success",
        "Support Specialist",
        "ou_acme_cs_lead",
        ["sofia", "support"],
    ),
]


EMPLOYEE_BY_OPEN_ID = {employee["open_id"]: employee for employee in EMPLOYEES}

CHAT_LABELS = {
    "oc_acme_launch": "Q2 Growth Launch War Room",
    "oc_acme_risk": "Risk & Security Review",
    "oc_acme_cutover": "Data Migration Cutover",
    "oc_acme_incident": "Incident SEV-2 Payment Callback",
    "oc_acme_finance": "Finance Approval Desk",
    "oc_acme_beta": "Customer Beta Escalations",
    "oc_acme_enablement": "Launch Docs & Enablement",
}

THREAD_LABELS = {
    "th_launch": "Q2 Growth Launch",
    "th_risk": "Security and Legal Risk Review",
    "th_cutover": "Warehouse Migration Cutover",
    "th_incident": "SEV-2 Payment Callback",
    "th_finance": "Budget and Vendor Approval",
    "th_beta": "Beta Customer Escalations",
    "th_enablement": "Launch Enablement Materials",
}


@dataclass(frozen=True)
class EventSeed:
    day: int
    hour: int
    minute: int
    chat_id: str
    thread_id: str
    sender_open_id: str
    message_type: str
    content_text: str
    key: str = ""
    mentions: list[str] = field(default_factory=list)
    attachments: list[dict[str, Any]] = field(default_factory=list)
    doc_refs: list[dict[str, Any]] = field(default_factory=list)
    task_refs: list[dict[str, Any]] = field(default_factory=list)
    approval_refs: list[dict[str, Any]] = field(default_factory=list)
    card_payload: dict[str, Any] | None = None
    relations: list[dict[str, Any]] = field(default_factory=list)


def _task(task_id: str, *, status: str = "", owner: str = "", blocked_by: str = "") -> dict[str, Any]:
    row: dict[str, Any] = {"id": task_id}
    if status:
        row["status"] = status
    if owner:
        row["owner_open_id"] = owner
    if blocked_by:
        row["blocked_by"] = blocked_by
    return row


def _approval(approval_id: str, *, status: str, approved_by: str = "") -> dict[str, Any]:
    row: dict[str, Any] = {"id": approval_id, "status": status}
    if approved_by:
        row["approved_by"] = approved_by
    return row


def _doc(doc_id: str, title: str) -> dict[str, Any]:
    return {"id": doc_id, "title": title}


def _file(file_id: str, name: str) -> dict[str, Any]:
    return {"id": file_id, "name": name}


def _card(title: str, status: str, fields: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"title": title, "status": status, "fields": fields or {}}


def _rel(relation_type: str, source: str, target: str) -> dict[str, Any]:
    return {"type": relation_type, "source": source, "target": target}


EVENT_SEEDS: list[EventSeed] = [
    EventSeed(1, 9, 0, "oc_acme_launch", "th_launch", "ou_acme_cpo", "text", "Kickoff for Q2 Growth Launch: keep PRD, risk review, finance approval, beta escalations, and enablement in one tracked launch lane.", "launch_kickoff", ["ou_acme_product_pm", "ou_acme_eng_mgr", "ou_acme_marketing", "ou_acme_ops_head"], doc_refs=[_doc("doc:prd_q2_growth", "Q2 Growth Launch PRD")], task_refs=[_task("PROD-410", status="planned", owner="ou_acme_product_pm")]),
    EventSeed(1, 9, 20, "oc_acme_launch", "th_launch", "ou_acme_product_pm", "post", "PRD v0.9 is ready. Decision log says launch target is Apr 18 unless security or finance blocks it.", "prd_v09", ["ou_acme_security_lead", "ou_acme_cfo"], doc_refs=[_doc("doc:prd_q2_growth", "Q2 Growth Launch PRD")], task_refs=[_task("PROD-410", status="in_progress", owner="ou_acme_product_pm")]),
    EventSeed(1, 10, 5, "oc_acme_launch", "th_launch", "ou_acme_eng_mgr", "text", "Engineering split: ENG-287 owns entitlement API, Owen owns UI flag copy, Priya owns payment callback compatibility.", "eng_split", ["ou_acme_backend", "ou_acme_frontend"], task_refs=[_task("ENG-287", status="in_progress", owner="ou_acme_backend")]),
    EventSeed(1, 10, 40, "oc_acme_launch", "th_launch", "ou_acme_design", "file", "Attached the launch surface redlines. The empty state text still references the old Growth Lab name.", "design_redlines", attachments=[_file("file:launch_surface_redlines_v1", "launch_surface_redlines_v1.fig")], task_refs=[_task("MKT-155", status="planned", owner="ou_acme_marketing")]),
    EventSeed(1, 11, 15, "oc_acme_risk", "th_risk", "ou_acme_security_lead", "text", "Opening SEC-072 for token scope review. PROD-410 should be treated as blocked until SEC-072 is cleared.", "risk_open", ["ou_acme_product_pm", "ou_acme_seceng"], doc_refs=[_doc("doc:risk_register", "Q2 Launch Risk Register")], task_refs=[_task("SEC-072", status="open", owner="ou_acme_security_lead"), _task("PROD-410", status="blocked", owner="ou_acme_product_pm", blocked_by="SEC-072")]),
    EventSeed(1, 13, 0, "oc_acme_finance", "th_finance", "ou_acme_finance_ops", "approval", "AP-724 opened for LaunchDarkly overage and beta support credits. FIN-204 is pending AP-724.", "finance_open_ap724", ["ou_acme_cfo"], task_refs=[_task("FIN-204", status="pending_approval", owner="ou_acme_finance_ops", blocked_by="AP-724")], approval_refs=[_approval("AP-724", status="pending")]),
    EventSeed(1, 14, 25, "oc_acme_beta", "th_beta", "ou_acme_cs_lead", "text", "Northstar and Atlas asked for beta access. CS-331 tracks the rollout list and support script.", "beta_requests", ["ou_acme_product_pm", "ou_acme_support"], task_refs=[_task("CS-331", status="in_progress", owner="ou_acme_cs_lead")]),
    EventSeed(1, 15, 10, "oc_acme_enablement", "th_enablement", "ou_acme_marketing", "post", "Enablement plan draft is in the deck. It still depends on final launch date and approved pricing language.", "enablement_draft", ["ou_acme_legal", "ou_acme_product_pm"], doc_refs=[_doc("doc:enablement_plan", "Q2 Launch Enablement Plan")], attachments=[_file("file:enablement_deck_v1", "q2_launch_enablement_v1.pptx")], task_refs=[_task("MKT-155", status="in_progress", owner="ou_acme_marketing", blocked_by="PROD-410")]),
    EventSeed(2, 9, 10, "oc_acme_cutover", "th_cutover", "ou_acme_data_lead", "text", "DATA-118 starts today: move beta analytics to warehouse v2. Cutover owner is Victor, reviewer is Iris.", "cutover_start", ["ou_acme_data_eng", "ou_acme_sre"], doc_refs=[_doc("doc:data_migration_plan", "Warehouse v2 Migration Plan")], task_refs=[_task("DATA-118", status="in_progress", owner="ou_acme_data_eng")]),
    EventSeed(2, 10, 0, "oc_acme_risk", "th_risk", "ou_acme_seceng", "comment", "Security finding: one webhook scope is broader than needed. SEC-072 is blocked by AP-710 because Legal must approve the compensating control language.", "sec_blocked_by_ap710", ["ou_acme_legal"], doc_refs=[_doc("doc:risk_register", "Q2 Launch Risk Register")], task_refs=[_task("SEC-072", status="blocked", owner="ou_acme_security_lead", blocked_by="AP-710")], approval_refs=[_approval("AP-710", status="pending")]),
    EventSeed(2, 11, 30, "oc_acme_launch", "th_launch", "ou_acme_product_pm", "text", "Current status: PROD-410 is still blocked because SEC-072 waits on AP-710. Do not announce Apr 18 publicly yet.", "launch_blocked_summary", ["ou_acme_marketing"], task_refs=[_task("PROD-410", status="blocked", owner="ou_acme_product_pm", blocked_by="SEC-072"), _task("SEC-072", status="blocked", owner="ou_acme_security_lead", blocked_by="AP-710")]),
    EventSeed(2, 13, 45, "oc_acme_incident", "th_incident", "ou_acme_sre", "system", "Monitor opened SEV-2: payment callback retries spiked after the sandbox merchant replay. Incident task OPS-099 created.", "incident_open", ["ou_acme_backend", "ou_acme_ops_head"], task_refs=[_task("OPS-099", status="open", owner="ou_acme_sre")], card_payload=_card("SEV-2 payment callback retries", "open", {"severity": "sev2"})),
    EventSeed(2, 14, 5, "oc_acme_incident", "th_incident", "ou_acme_backend", "text", "Initial suspicion was LaunchDarkly flag evaluation, but traces show duplicate PSP callback IDs. ENG-287 is not the root cause.", "incident_not_flag", ["ou_acme_eng_mgr"], task_refs=[_task("ENG-287", status="in_progress", owner="ou_acme_backend"), _task("OPS-099", status="investigating", owner="ou_acme_sre")]),
    EventSeed(2, 16, 0, "oc_acme_finance", "th_finance", "ou_acme_cfo", "approval", "AP-724 is approved for the overage and support credits. FIN-204 can move to ready.", "finance_ap724_approved", ["ou_acme_finance_ops"], task_refs=[_task("FIN-204", status="ready", owner="ou_acme_finance_ops")], approval_refs=[_approval("AP-724", status="approved", approved_by="ou_acme_cfo")]),
    EventSeed(3, 9, 0, "oc_acme_cutover", "th_cutover", "ou_acme_data_eng", "text", "Backfill batch 1 finished with 99.7 percent parity. DATA-118 remains in progress until revenue cohort joins reconcile.", "cutover_batch1", ["ou_acme_data_lead"], task_refs=[_task("DATA-118", status="in_progress", owner="ou_acme_data_eng")]),
    EventSeed(3, 10, 15, "oc_acme_incident", "th_incident", "ou_acme_sre", "text", "Temporary rate limit is live. OPS-099 moves from investigating to mitigated, pending postmortem and replay cleanup.", "incident_mitigated", ["ou_acme_release"], task_refs=[_task("OPS-099", status="mitigated", owner="ou_acme_sre")], doc_refs=[_doc("doc:sev2_payment_callback_postmortem", "SEV-2 Payment Callback Postmortem")]),
    EventSeed(3, 11, 40, "oc_acme_beta", "th_beta", "ou_acme_support", "text", "Atlas says the welcome email points to the old dashboard. I added it to CS-331 notes.", "beta_atlas_email", ["ou_acme_marketing"], task_refs=[_task("CS-331", status="in_progress", owner="ou_acme_cs_lead")]),
    EventSeed(3, 14, 0, "oc_acme_risk", "th_risk", "ou_acme_legal", "approval", "AP-710 approved with the condition that the release note names the narrow token scope. SEC-072 can resume.", "ap710_approved", ["ou_acme_security_lead"], approval_refs=[_approval("AP-710", status="approved", approved_by="ou_acme_legal")], task_refs=[_task("SEC-072", status="in_progress", owner="ou_acme_security_lead")]),
    EventSeed(3, 15, 20, "oc_acme_launch", "th_launch", "ou_acme_product_pm", "text", "Update after Legal approval: PROD-410 is no longer blocked by AP-710 directly, but still waits for Grace to close SEC-072.", "prod_waits_sec_close", ["ou_acme_security_lead", "ou_acme_marketing"], task_refs=[_task("PROD-410", status="blocked", owner="ou_acme_product_pm", blocked_by="SEC-072")]),
    EventSeed(4, 9, 30, "oc_acme_risk", "th_risk", "ou_acme_security_lead", "text", "SEC-072 closed. Token scope language is in the risk register and release note. PROD-410 security block is removed.", "sec072_closed", ["ou_acme_product_pm"], doc_refs=[_doc("doc:risk_register", "Q2 Launch Risk Register")], task_refs=[_task("SEC-072", status="done", owner="ou_acme_security_lead"), _task("PROD-410", status="in_progress", owner="ou_acme_product_pm")]),
    EventSeed(4, 10, 10, "oc_acme_launch", "th_launch", "ou_acme_cpo", "text", "Decision: launch date moves from Apr 18 to Apr 22 because DATA-118 parity and enablement need one more cycle.", "launch_date_moved", ["ou_acme_marketing", "ou_acme_ops_head"], task_refs=[_task("PROD-410", status="in_progress", owner="ou_acme_product_pm"), _task("DATA-118", status="in_progress", owner="ou_acme_data_eng")], relations=[_rel("blocked_by", "task:MKT-155", "task:PROD-410")]),
    EventSeed(4, 13, 0, "oc_acme_enablement", "th_enablement", "ou_acme_marketing", "text", "The enablement deck must say Apr 22, not Apr 18. I am updating MKT-155 and the customer FAQ.", "enablement_date_change", ["ou_acme_support"], attachments=[_file("file:enablement_deck_v2", "q2_launch_enablement_v2.pptx")], task_refs=[_task("MKT-155", status="in_progress", owner="ou_acme_marketing", blocked_by="PROD-410")]),
    EventSeed(4, 16, 15, "oc_acme_cutover", "th_cutover", "ou_acme_sre", "comment", "Iris review: cutover runbook needs rollback owner before DATA-118 can be marked ready.", "cutover_needs_rollback", ["ou_acme_data_eng", "ou_acme_release"], doc_refs=[_doc("doc:data_migration_plan", "Warehouse v2 Migration Plan")], task_refs=[_task("DATA-118", status="blocked", owner="ou_acme_data_eng", blocked_by="OPS-099")]),
    EventSeed(5, 9, 10, "oc_acme_incident", "th_incident", "ou_acme_release", "post", "Postmortem draft says duplicate PSP callback IDs caused the spike. Tom owns replay cleanup, Iris owns monitor threshold update.", "postmortem_owner_split", ["ou_acme_sre"], doc_refs=[_doc("doc:sev2_payment_callback_postmortem", "SEV-2 Payment Callback Postmortem")], task_refs=[_task("OPS-099", status="in_progress", owner="ou_acme_release")]),
    EventSeed(5, 11, 30, "oc_acme_cutover", "th_cutover", "ou_acme_data_lead", "text", "Ownership change: DATA-118 moves from Victor to Hannah for the final cutover call because Victor is on-call for replay cleanup.", "data_owner_change", ["ou_acme_data_eng", "ou_acme_sre"], task_refs=[_task("DATA-118", status="in_progress", owner="ou_acme_data_lead")]),
    EventSeed(5, 14, 0, "oc_acme_beta", "th_beta", "ou_acme_cs_lead", "text", "Northstar beta can proceed after Apr 22 launch. Atlas remains blocked on old-dashboard email copy in MKT-155.", "beta_split_status", ["ou_acme_marketing"], task_refs=[_task("CS-331", status="in_progress", owner="ou_acme_cs_lead"), _task("MKT-155", status="in_progress", owner="ou_acme_marketing", blocked_by="PROD-410")]),
    EventSeed(6, 9, 20, "oc_acme_finance", "th_finance", "ou_acme_finance_ops", "text", "Finance has PO coverage now. FIN-204 is done; no remaining budget blocker for launch.", "fin204_done", ["ou_acme_product_pm"], task_refs=[_task("FIN-204", status="done", owner="ou_acme_finance_ops")]),
    EventSeed(6, 10, 5, "oc_acme_incident", "th_incident", "ou_acme_sre", "text", "Replay cleanup complete. OPS-099 is closed and no longer blocks DATA-118 rollback planning.", "ops099_closed", ["ou_acme_data_lead"], task_refs=[_task("OPS-099", status="done", owner="ou_acme_release"), _task("DATA-118", status="in_progress", owner="ou_acme_data_lead")]),
    EventSeed(6, 13, 35, "oc_acme_cutover", "th_cutover", "ou_acme_data_lead", "text", "DATA-118 is ready. Rollback owner is Iris, go/no-go owner is Hannah, and parity reached 99.95 percent.", "data118_ready", ["ou_acme_sre", "ou_acme_release"], task_refs=[_task("DATA-118", status="ready", owner="ou_acme_data_lead")]),
    EventSeed(7, 9, 0, "oc_acme_launch", "th_launch", "ou_acme_product_pm", "text", "Launch checklist v1: security done, finance done, data ready, incident closed. Remaining blockers are MKT-155 customer copy and AP-731 legal approval.", "launch_checklist_v1", ["ou_acme_marketing", "ou_acme_legal"], doc_refs=[_doc("doc:launch_checklist", "Q2 Launch Checklist")], task_refs=[_task("PROD-410", status="ready", owner="ou_acme_product_pm"), _task("MKT-155", status="blocked", owner="ou_acme_marketing", blocked_by="AP-731")], approval_refs=[_approval("AP-731", status="pending")]),
    EventSeed(7, 10, 20, "oc_acme_enablement", "th_enablement", "ou_acme_legal", "comment", "AP-731 legal review: change 'guaranteed uplift' to 'observed uplift in beta accounts' before approval.", "ap731_requested_change", ["ou_acme_marketing"], doc_refs=[_doc("doc:customer_faq", "Customer FAQ")], approval_refs=[_approval("AP-731", status="changes_requested")], task_refs=[_task("MKT-155", status="blocked", owner="ou_acme_marketing", blocked_by="AP-731")]),
    EventSeed(7, 13, 30, "oc_acme_enablement", "th_enablement", "ou_acme_marketing", "text", "Updated FAQ and deck language per Ava: 'observed uplift in beta accounts'. AP-731 is ready for re-review.", "marketing_revised_copy", ["ou_acme_legal"], attachments=[_file("file:enablement_deck_v3", "q2_launch_enablement_v3.pptx")], doc_refs=[_doc("doc:customer_faq", "Customer FAQ")], task_refs=[_task("MKT-155", status="review", owner="ou_acme_marketing", blocked_by="AP-731")], approval_refs=[_approval("AP-731", status="pending")]),
    EventSeed(8, 9, 45, "oc_acme_enablement", "th_enablement", "ou_acme_legal", "approval", "AP-731 approved. The approved wording is 'observed uplift in beta accounts'. MKT-155 can close after CS signoff.", "ap731_approved", ["ou_acme_marketing", "ou_acme_cs_lead"], approval_refs=[_approval("AP-731", status="approved", approved_by="ou_acme_legal")], task_refs=[_task("MKT-155", status="in_progress", owner="ou_acme_marketing")]),
    EventSeed(8, 11, 0, "oc_acme_beta", "th_beta", "ou_acme_support", "text", "CS signoff complete for Northstar and Atlas scripts. CS-331 can close once launch email goes out.", "cs_signoff", ["ou_acme_marketing"], task_refs=[_task("CS-331", status="ready", owner="ou_acme_cs_lead"), _task("MKT-155", status="in_progress", owner="ou_acme_marketing")]),
    EventSeed(8, 15, 15, "oc_acme_launch", "th_launch", "ou_acme_cpo", "card", "Launch readiness card: all primary blockers cleared. Final go/no-go remains Apr 21 16:00.", "readiness_card_all_clear", ["ou_acme_ceo"], task_refs=[_task("PROD-410", status="ready", owner="ou_acme_product_pm"), _task("DATA-118", status="ready", owner="ou_acme_data_lead"), _task("FIN-204", status="done", owner="ou_acme_finance_ops"), _task("MKT-155", status="in_progress", owner="ou_acme_marketing")], card_payload=_card("Q2 Growth Launch Readiness", "green", {"go_no_go": "2026-04-21T16:00:00Z"})),
    EventSeed(9, 9, 30, "oc_acme_enablement", "th_enablement", "ou_acme_marketing", "text", "MKT-155 closed. Deck v3 and FAQ are approved; support script is linked from enablement plan.", "mkt155_done", ["ou_acme_cs_lead"], doc_refs=[_doc("doc:enablement_plan", "Q2 Launch Enablement Plan"), _doc("doc:customer_faq", "Customer FAQ")], attachments=[_file("file:enablement_deck_v3", "q2_launch_enablement_v3.pptx")], task_refs=[_task("MKT-155", status="done", owner="ou_acme_marketing")]),
    EventSeed(9, 13, 0, "oc_acme_beta", "th_beta", "ou_acme_cs_lead", "text", "CS-331 closed. Northstar and Atlas contacts are tagged for Apr 22 launch email, with Sofia on first-response duty.", "cs331_done", ["ou_acme_support"], task_refs=[_task("CS-331", status="done", owner="ou_acme_cs_lead")]),
    EventSeed(10, 9, 0, "oc_acme_launch", "th_launch", "ou_acme_ops_head", "text", "Ops check: launch date is still Apr 22. Tom owns release command; Rachel owns executive comms.", "ops_launch_check", ["ou_acme_release", "ou_acme_ceo"], task_refs=[_task("PROD-410", status="ready", owner="ou_acme_product_pm")]),
    EventSeed(10, 10, 30, "oc_acme_launch", "th_launch", "ou_acme_ceo", "text", "Executive go/no-go: approved for Apr 22, contingent on no new SEV-1 or security blocker before launch window.", "exec_go", ["ou_acme_cpo", "ou_acme_cto", "ou_acme_ops_head"], task_refs=[_task("PROD-410", status="approved", owner="ou_acme_product_pm")]),
    EventSeed(10, 16, 0, "oc_acme_launch", "th_launch", "ou_acme_release", "system", "Release window scheduled: Apr 22 09:00 UTC. Rollback owner Iris, launch PM Alice, comms Zoe.", "release_window_scheduled", ["ou_acme_sre", "ou_acme_product_pm", "ou_acme_marketing"], task_refs=[_task("PROD-410", status="scheduled", owner="ou_acme_product_pm"), _task("DATA-118", status="scheduled", owner="ou_acme_data_lead")]),
    EventSeed(11, 9, 0, "oc_acme_cutover", "th_cutover", "ou_acme_data_lead", "system", "Warehouse v2 cutover started. DATA-118 entering launch window; old dashboard export remains read-only.", "cutover_started", ["ou_acme_sre"], task_refs=[_task("DATA-118", status="deploying", owner="ou_acme_data_lead")], card_payload=_card("Warehouse v2 cutover", "deploying")),
    EventSeed(11, 9, 30, "oc_acme_launch", "th_launch", "ou_acme_release", "system", "Q2 Growth Launch started. Feature flag at 10 percent for beta cohorts.", "launch_started", ["ou_acme_product_pm", "ou_acme_backend"], task_refs=[_task("PROD-410", status="deploying", owner="ou_acme_product_pm")], card_payload=_card("Q2 Growth Launch", "deploying", {"flag": "10%"})),
    EventSeed(11, 10, 15, "oc_acme_incident", "th_incident", "ou_acme_sre", "text", "Payment callback monitors are quiet during launch. Previous SEV-2 fix is holding.", "incident_monitor_quiet", ["ou_acme_release"], task_refs=[_task("OPS-099", status="done", owner="ou_acme_release")]),
    EventSeed(11, 11, 45, "oc_acme_launch", "th_launch", "ou_acme_backend", "text", "Entitlement API steady at 50 percent. No duplicate callback regression. ENG-287 can move to done after 100 percent.", "eng287_steady", ["ou_acme_eng_mgr"], task_refs=[_task("ENG-287", status="verifying", owner="ou_acme_backend")]),
    EventSeed(11, 13, 15, "oc_acme_cutover", "th_cutover", "ou_acme_data_eng", "text", "Warehouse v2 parity is 99.98 percent after live traffic. No rollback needed.", "cutover_live_parity", ["ou_acme_data_lead"], task_refs=[_task("DATA-118", status="verifying", owner="ou_acme_data_lead")]),
    EventSeed(11, 15, 40, "oc_acme_launch", "th_launch", "ou_acme_release", "system", "Feature flag reached 100 percent. PROD-410 launch is complete.", "prod410_complete", ["ou_acme_cpo"], task_refs=[_task("PROD-410", status="done", owner="ou_acme_product_pm")], card_payload=_card("Q2 Growth Launch", "complete", {"flag": "100%"})),
    EventSeed(12, 9, 20, "oc_acme_cutover", "th_cutover", "ou_acme_data_lead", "text", "DATA-118 closed. Warehouse v2 dashboard is source of truth for beta analytics from today.", "data118_done", ["ou_acme_cpo"], task_refs=[_task("DATA-118", status="done", owner="ou_acme_data_lead")]),
    EventSeed(12, 10, 10, "oc_acme_launch", "th_launch", "ou_acme_eng_mgr", "text", "ENG-287 done. Priya documented the callback compatibility note in the runbook.", "eng287_done", ["ou_acme_backend"], doc_refs=[_doc("doc:launch_runbook", "Q2 Launch Runbook")], task_refs=[_task("ENG-287", status="done", owner="ou_acme_backend")]),
    EventSeed(12, 11, 30, "oc_acme_beta", "th_beta", "ou_acme_support", "text", "Northstar replied positively; Atlas still needs SSO mapping help, but that is post-launch support and not a launch blocker.", "post_launch_beta_support", ["ou_acme_cs_lead"], task_refs=[_task("CS-331", status="done", owner="ou_acme_cs_lead")]),
    EventSeed(12, 14, 0, "oc_acme_launch", "th_launch", "ou_acme_cpo", "post", "Final launch status: PROD-410, ENG-287, DATA-118, FIN-204, MKT-155, CS-331, SEC-072, and OPS-099 are all done. Launch date was Apr 22.", "final_launch_status", ["ou_acme_ceo"], doc_refs=[_doc("doc:launch_checklist", "Q2 Launch Checklist")], task_refs=[_task("PROD-410", status="done", owner="ou_acme_product_pm"), _task("ENG-287", status="done", owner="ou_acme_backend"), _task("DATA-118", status="done", owner="ou_acme_data_lead"), _task("FIN-204", status="done", owner="ou_acme_finance_ops"), _task("MKT-155", status="done", owner="ou_acme_marketing"), _task("CS-331", status="done", owner="ou_acme_cs_lead"), _task("SEC-072", status="done", owner="ou_acme_security_lead"), _task("OPS-099", status="done", owner="ou_acme_release")]),
]


def _status_by_day(day: int, *, early: str, middle: str, late: str, done: str = "done") -> str:
    if day <= 3:
        return early
    if day <= 7:
        return middle
    if day <= 10:
        return late
    return done


def _supporting_event_seeds() -> list[EventSeed]:
    seeds: list[EventSeed] = []
    for day in range(1, 13):
        launch_status = _status_by_day(day, early="in_progress", middle="blocked", late="ready")
        if day >= 11:
            launch_status = "deploying" if day == 11 else "done"
        seeds.append(
            EventSeed(
                day,
                8,
                45,
                "oc_acme_launch",
                "th_launch",
                "ou_acme_product_pm" if day % 2 else "ou_acme_release",
                "bot_notice" if day == 11 else "text",
                f"Daily launch pulse day {day}: tracking PROD-410 as {launch_status}; watch security, data, finance, enablement, and CS dependencies before changing public comms.",
                mentions=["ou_acme_marketing", "ou_acme_ops_head"],
                doc_refs=[_doc("doc:launch_checklist", "Q2 Launch Checklist")],
                task_refs=[_task("PROD-410", status=launch_status, owner="ou_acme_product_pm")],
            )
        )

    for day in range(1, 9):
        status = "blocked" if day in {2, 3} else ("done" if day >= 4 else "open")
        seeds.append(
            EventSeed(
                day,
                12,
                10,
                "oc_acme_risk",
                "th_risk",
                "ou_acme_security_lead" if day % 2 else "ou_acme_seceng",
                "document" if day == 4 else "comment",
                f"Risk review pulse day {day}: SEC-072 status is {status}; keep token scope notes in the risk register and do not rely on stale launch-date notes.",
                mentions=["ou_acme_product_pm"],
                doc_refs=[_doc("doc:risk_register", "Q2 Launch Risk Register")],
                task_refs=[_task("SEC-072", status=status, owner="ou_acme_security_lead")],
            )
        )

    for day in range(2, 13):
        owner = "ou_acme_data_eng" if day < 5 else "ou_acme_data_lead"
        status = _status_by_day(day, early="in_progress", middle="blocked", late="ready")
        if day >= 11:
            status = "deploying" if day == 11 else "done"
        seeds.append(
            EventSeed(
                day,
                12,
                25,
                "oc_acme_cutover",
                "th_cutover",
                owner,
                "text",
                f"Warehouse migration pulse day {day}: DATA-118 is {status}; parity, rollback ownership, and dashboard source-of-truth notes remain tracked in the migration plan.",
                mentions=["ou_acme_sre"],
                doc_refs=[_doc("doc:data_migration_plan", "Warehouse v2 Migration Plan")],
                task_refs=[_task("DATA-118", status=status, owner=owner)],
            )
        )

    for day in range(1, 10):
        status = "blocked" if day in {4, 7} else ("done" if day == 9 else "in_progress")
        seeds.append(
            EventSeed(
                day,
                16,
                30,
                "oc_acme_enablement",
                "th_enablement",
                "ou_acme_marketing",
                "document" if day == 7 else "text",
                f"Enablement pulse day {day}: MKT-155 is {status}; deck, FAQ, and support script must stay aligned with the latest launch date and legal wording.",
                mentions=["ou_acme_cs_lead", "ou_acme_legal"],
                doc_refs=[_doc("doc:enablement_plan", "Q2 Launch Enablement Plan")],
                task_refs=[_task("MKT-155", status=status, owner="ou_acme_marketing")],
            )
        )

    for day in range(1, 13):
        status = "done" if day >= 9 else ("ready" if day == 8 else "in_progress")
        seeds.append(
            EventSeed(
                day,
                16,
                45,
                "oc_acme_beta",
                "th_beta",
                "ou_acme_cs_lead" if day % 2 else "ou_acme_support",
                "text",
                f"CS beta pulse day {day}: CS-331 is {status}; Northstar and Atlas updates should be routed through the support script instead of ad hoc launch promises.",
                mentions=["ou_acme_marketing"],
                task_refs=[_task("CS-331", status=status, owner="ou_acme_cs_lead")],
            )
        )
    return seeds


def _all_event_seeds() -> list[EventSeed]:
    return sorted(
        [*EVENT_SEEDS, *_supporting_event_seeds()],
        key=lambda seed: (seed.day, seed.hour, seed.minute, seed.chat_id, seed.thread_id, seed.sender_open_id),
    )


def _event_time(seed: EventSeed) -> str:
    start = datetime(2026, 4, 1, tzinfo=timezone.utc)
    value = start + timedelta(days=seed.day - 1, hours=seed.hour, minutes=seed.minute)
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_acme_q2_ops_events(snapshot_id: str = ACME_Q2_OPS_SNAPSHOT_ID) -> tuple[list[dict[str, Any]], dict[str, str]]:
    events: list[dict[str, Any]] = []
    event_id_by_key: dict[str, str] = {}
    thread_root_message_id: dict[str, str] = {}

    for index, seed in enumerate(_all_event_seeds(), start=1):
        event_id = f"evt_acme_q2_{index:04d}"
        message_id = f"om_acme_q2_{index:04d}"
        reply_to_message_id = thread_root_message_id.get(seed.thread_id, "")
        thread_root_message_id.setdefault(seed.thread_id, message_id)
        if seed.key:
            event_id_by_key[seed.key] = event_id
        employee = EMPLOYEE_BY_OPEN_ID[seed.sender_open_id]
        event = normalize_office_event(
            {
                "event_id": event_id,
                "snapshot_id": snapshot_id,
                "workspace_id": ACME_WORKSPACE_ID,
                "chat_id": seed.chat_id,
                "thread_id": seed.thread_id,
                "message_id": message_id,
                "reply_to_message_id": reply_to_message_id,
                "event_time": _event_time(seed),
                "sender_open_id": seed.sender_open_id,
                "sender_name": employee["name"],
                "message_type": seed.message_type,
                "content_text": seed.content_text,
                "mentions": seed.mentions,
                "attachments": seed.attachments,
                "doc_refs": seed.doc_refs,
                "task_refs": seed.task_refs,
                "approval_refs": seed.approval_refs,
                "card_payload": seed.card_payload,
                "raw_event_ref": {
                    "source": "deterministic_fixture",
                    "chat_label": CHAT_LABELS[seed.chat_id],
                    "thread_label": THREAD_LABELS[seed.thread_id],
                    "seed_key": seed.key,
                },
                "direction": "inbound",
                "chat_type": "group",
                "entity_refs": [
                    {"id": f"chat:{seed.chat_id}", "label": CHAT_LABELS[seed.chat_id]},
                    {"id": f"thread:{seed.thread_id}", "label": THREAD_LABELS[seed.thread_id]},
                ],
                "relations": seed.relations,
            },
            snapshot_id=snapshot_id,
        )
        events.append(event)

    return events, event_id_by_key


def _history_window(*, chat_ids: list[str] | None = None, thread_ids: list[str] | None = None) -> dict[str, Any]:
    return {
        "event_ids": [],
        "start_time": "2026-04-01T09:00:00Z",
        "end_time": "2026-04-12T14:00:00Z",
        "chat_ids": chat_ids or [],
        "thread_ids": thread_ids or [],
        "max_events": 120,
    }


def build_acme_q2_ops_validation_manifest(
    event_id_by_key: dict[str, str],
    *,
    snapshot_id: str = ACME_Q2_OPS_SNAPSHOT_ID,
) -> dict[str, Any]:
    def ids(*keys: str) -> list[str]:
        return [event_id_by_key[key] for key in keys]

    cases = [
        {
            "case_id": "acme-q2-001-final-launch-status",
            "history_window": _history_window(chat_ids=["oc_acme_launch"]),
            "question": "What is the final status of the Q2 Growth Launch and which key workstreams are done?",
            "expected_answer": "The Q2 Growth Launch completed on Apr 22. PROD-410, ENG-287, DATA-118, FIN-204, MKT-155, CS-331, SEC-072, and OPS-099 are all done.",
            "evidence_event_ids": ids("prod410_complete", "final_launch_status"),
            "ability_tag": "long_horizon_status",
        },
        {
            "case_id": "acme-q2-002-security-block-chain",
            "history_window": _history_window(chat_ids=["oc_acme_launch", "oc_acme_risk"]),
            "question": "What was the blocking chain behind PROD-410 early in the launch?",
            "expected_answer": "PROD-410 was blocked by SEC-072, and SEC-072 was blocked by AP-710 until Legal approved AP-710.",
            "evidence_event_ids": ids("risk_open", "sec_blocked_by_ap710", "ap710_approved", "sec072_closed"),
            "ability_tag": "blocked_by_chain",
        },
        {
            "case_id": "acme-q2-003-data-owner-change",
            "history_window": _history_window(chat_ids=["oc_acme_cutover", "oc_acme_incident"]),
            "question": "Who owned DATA-118 at the final cutover call and why did ownership change?",
            "expected_answer": "Hannah Zhao owned DATA-118 for the final cutover call because Victor Huang was on-call for replay cleanup.",
            "evidence_event_ids": ids("data_owner_change", "data118_ready", "data118_done"),
            "ability_tag": "owner_change",
        },
        {
            "case_id": "acme-q2-004-incident-root-cause",
            "history_window": _history_window(chat_ids=["oc_acme_incident", "oc_acme_launch"]),
            "question": "Was ENG-287 the root cause of the SEV-2 payment callback incident?",
            "expected_answer": "No. The initial flag suspicion was ruled out; duplicate PSP callback IDs caused the incident.",
            "evidence_event_ids": ids("incident_not_flag", "postmortem_owner_split"),
            "ability_tag": "stale_info_resolution",
        },
        {
            "case_id": "acme-q2-005-finance-approval",
            "history_window": _history_window(chat_ids=["oc_acme_finance", "oc_acme_launch"]),
            "question": "What happened to AP-724 and did finance remain a launch blocker?",
            "expected_answer": "AP-724 was approved by Claire Dubois, FIN-204 moved to ready and then done, so finance was no longer a launch blocker.",
            "evidence_event_ids": ids("finance_open_ap724", "finance_ap724_approved", "fin204_done"),
            "ability_tag": "approval_progression",
        },
        {
            "case_id": "acme-q2-006-legal-copy",
            "history_window": _history_window(chat_ids=["oc_acme_enablement"]),
            "question": "What exact customer-facing wording did Legal approve for the uplift claim?",
            "expected_answer": "Legal approved the wording 'observed uplift in beta accounts'.",
            "evidence_event_ids": ids("ap731_requested_change", "marketing_revised_copy", "ap731_approved"),
            "ability_tag": "doc_reference",
        },
        {
            "case_id": "acme-q2-007-launch-date",
            "history_window": _history_window(chat_ids=["oc_acme_launch", "oc_acme_enablement"]),
            "question": "What was the final launch date after the date change, and what stale date should be ignored?",
            "expected_answer": "The final launch date was Apr 22; the earlier Apr 18 target should be ignored.",
            "evidence_event_ids": ids("prd_v09", "launch_date_moved", "ops_launch_check", "final_launch_status"),
            "ability_tag": "temporal_reasoning",
        },
        {
            "case_id": "acme-q2-008-enable-deck-file",
            "history_window": _history_window(chat_ids=["oc_acme_enablement"]),
            "question": "Which enablement deck version was approved for launch?",
            "expected_answer": "The approved enablement deck was q2_launch_enablement_v3.pptx.",
            "evidence_event_ids": ids("marketing_revised_copy", "mkt155_done"),
            "ability_tag": "file_reference",
        },
        {
            "case_id": "acme-q2-009-beta-customers",
            "history_window": _history_window(chat_ids=["oc_acme_beta", "oc_acme_enablement"]),
            "question": "What happened with Northstar and Atlas beta communications by the end?",
            "expected_answer": "CS-331 closed, Northstar and Atlas were tagged for the Apr 22 launch email, and Sofia was on first-response duty.",
            "evidence_event_ids": ids("beta_requests", "beta_split_status", "cs331_done"),
            "ability_tag": "cross_thread_relation",
        },
        {
            "case_id": "acme-q2-010-data-cutover-readiness",
            "history_window": _history_window(chat_ids=["oc_acme_cutover", "oc_acme_incident"]),
            "question": "What made DATA-118 ready after it had been blocked by rollback planning?",
            "expected_answer": "OPS-099 replay cleanup closed, rollback owner Iris was assigned, Hannah owned go/no-go, and parity reached 99.95 percent.",
            "evidence_event_ids": ids("cutover_needs_rollback", "ops099_closed", "data118_ready"),
            "ability_tag": "blocked_by_chain",
        },
        {
            "case_id": "acme-q2-011-go-no-go",
            "history_window": _history_window(chat_ids=["oc_acme_launch"]),
            "question": "Who approved executive go/no-go and what was the condition?",
            "expected_answer": "Elena Park approved go/no-go for Apr 22, contingent on no new SEV-1 or security blocker before the launch window.",
            "evidence_event_ids": ids("exec_go", "release_window_scheduled"),
            "ability_tag": "approval_progression",
        },
        {
            "case_id": "acme-q2-012-ops-release-roles",
            "history_window": _history_window(chat_ids=["oc_acme_launch"]),
            "question": "At the release window, who owned rollback, launch PM, and comms?",
            "expected_answer": "Iris Kim owned rollback, Alice Chen was launch PM, and Zoe Miller owned comms.",
            "evidence_event_ids": ids("release_window_scheduled"),
            "ability_tag": "multi_party_dependency",
        },
        {
            "case_id": "acme-q2-013-security-final",
            "history_window": _history_window(chat_ids=["oc_acme_risk", "oc_acme_launch"]),
            "question": "What was the final status of SEC-072 and where was the token scope language recorded?",
            "expected_answer": "SEC-072 was done, and the token scope language was recorded in the risk register and release note.",
            "evidence_event_ids": ids("ap710_approved", "sec072_closed", "final_launch_status"),
            "ability_tag": "doc_reference",
        },
        {
            "case_id": "acme-q2-014-graph-owner-status",
            "history_window": _history_window(),
            "question": "Which final task owners should the graph connect to PROD-410, DATA-118, MKT-155, and FIN-204?",
            "expected_answer": "PROD-410 belongs to Alice Chen, DATA-118 belongs to Hannah Zhao, MKT-155 belongs to Zoe Miller, and FIN-204 belongs to Mateo Rossi.",
            "evidence_event_ids": ids("final_launch_status", "data_owner_change", "mkt155_done", "fin204_done"),
            "ability_tag": "graph_hit",
        },
    ]
    return {
        "snapshot_id": snapshot_id,
        "description": "Reusable validation manifest for the Acme Q2 office fixture snapshot.",
        "cases": [
            normalize_validation_case(case, snapshot_id=snapshot_id)
            for case in cases
        ],
    }


def _metadata(snapshot_id: str, employees: list[dict[str, Any]], events: list[dict[str, Any]], cases: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot_id,
        "source": "deterministic_realistic_enterprise_fixture",
        "workspace_id": ACME_WORKSPACE_ID,
        "created_at": "2026-04-25T00:00:00Z",
        "frozen_at": "2026-04-25T00:00:00Z",
        "scenario": "B2B SaaS Q2 growth launch across product, engineering, security, data, finance, legal, marketing, and customer success.",
        "employees_version": {
            "employee_count": len(employees),
            "source": "eval.office_fixture_dataset.EMPLOYEES",
        },
        "validation_case_count": len(cases),
        "coverage": {
            "chats": CHAT_LABELS,
            "threads": THREAD_LABELS,
            "abilities": sorted({case["ability_tag"] for case in cases}),
            "message_types": sorted({event["message_type"] for event in events}),
        },
        "stats": {
            "event_count": len(events),
            "chat_count": len({event["chat_id"] for event in events}),
            "thread_count": len({event["thread_id"] for event in events}),
            "time_range": {
                "start": min(event["event_time"] for event in events),
                "end": max(event["event_time"] for event in events),
            },
        },
        "immutability": {
            "policy": "Do not edit this snapshot in place. Create a new snapshot_id for updates or Feishu capture output.",
            "validation_mode": "read_only_replay",
        },
    }


def write_acme_q2_ops_snapshot(
    *,
    root_dir: str | Path = "eval/office_dataset",
    snapshot_id: str = ACME_Q2_OPS_SNAPSHOT_ID,
) -> Path:
    root = Path(root_dir)
    snapshot_dir = root / "snapshots" / snapshot_id
    if snapshot_dir.exists():
        raise FileExistsError(f"Snapshot already exists and is immutable: {snapshot_dir}")

    snapshot_dir.mkdir(parents=True, exist_ok=False)
    employees = sorted(EMPLOYEES, key=lambda item: item["employee_id"])
    events, event_id_by_key = build_acme_q2_ops_events(snapshot_id=snapshot_id)
    manifest = build_acme_q2_ops_validation_manifest(event_id_by_key, snapshot_id=snapshot_id)

    dump_json({"employees": employees}, snapshot_dir / EMPLOYEES_JSON)
    export_employees_csv(employees, snapshot_dir / EMPLOYEES_CSV)
    dump_jsonl(events, snapshot_dir / OFFICE_EVENTS_JSONL)
    dump_json(manifest, snapshot_dir / VALIDATION_MANIFEST_JSON)
    dump_json(_metadata(snapshot_id, employees, events, manifest["cases"]), snapshot_dir / SNAPSHOT_METADATA_JSON)
    (snapshot_dir / SNAPSHOT_LOCK).write_text(
        f"snapshot_id={snapshot_id}\nfrozen_at=2026-04-25T00:00:00Z\n",
        encoding="utf-8",
    )
    return snapshot_dir


def read_employee_csv(path: str | Path) -> list[dict[str, str]]:
    with Path(path).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))
