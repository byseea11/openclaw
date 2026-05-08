"""Deterministic Chinese office snapshot fixture for OpenClaw evals."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from eval_old.office_dataset import (
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
from eval_old.scorers.common import dump_json, dump_jsonl

YUNHE_Q2_OPS_ZH_SNAPSHOT_ID = "yunhe_q2_ops_zh_v1"
YUNHE_WORKSPACE_ID = "feishu_test_workspace_yunhe_q2_ops_zh"


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


EMPLOYEES_ZH: list[dict[str, Any]] = [
    _employee("emp-yh-001", "ou_yh_ceo", "林若安", "dept-exec", "总经办", "CEO", aliases=["若安", "林总"]),
    _employee("emp-yh-002", "ou_yh_cpo", "周明澈", "dept-product", "产品部", "首席产品官", "ou_yh_ceo", ["明澈", "CPO"]),
    _employee("emp-yh-003", "ou_yh_product_pm", "陈雨薇", "dept-product", "产品部", "高级产品经理", "ou_yh_cpo", ["雨薇", "发布PM"]),
    _employee("emp-yh-004", "ou_yh_design", "许嘉宁", "dept-product", "产品部", "产品设计师", "ou_yh_cpo", ["嘉宁", "设计"]),
    _employee("emp-yh-005", "ou_yh_cto", "唐启航", "dept-engineering", "研发部", "CTO", "ou_yh_ceo", ["启航", "CTO"]),
    _employee("emp-yh-006", "ou_yh_eng_mgr", "李承泽", "dept-engineering", "研发部", "研发经理", "ou_yh_cto", ["承泽", "研发经理"]),
    _employee("emp-yh-007", "ou_yh_backend", "王昕然", "dept-engineering", "研发部", "后端工程师", "ou_yh_eng_mgr", ["昕然", "后端"]),
    _employee("emp-yh-008", "ou_yh_frontend", "赵一诺", "dept-engineering", "研发部", "前端工程师", "ou_yh_eng_mgr", ["一诺", "前端"]),
    _employee("emp-yh-009", "ou_yh_platform_mgr", "顾清远", "dept-platform", "平台部", "平台负责人", "ou_yh_cto", ["清远", "平台"]),
    _employee("emp-yh-010", "ou_yh_sre", "何知夏", "dept-platform", "平台部", "SRE", "ou_yh_platform_mgr", ["知夏", "SRE"]),
    _employee("emp-yh-011", "ou_yh_security_lead", "陆安琪", "dept-security", "安全部", "安全负责人", "ou_yh_cto", ["安琪", "安全"]),
    _employee("emp-yh-012", "ou_yh_seceng", "蒋亦凡", "dept-security", "安全部", "安全工程师", "ou_yh_security_lead", ["亦凡", "安全工程师"]),
    _employee("emp-yh-013", "ou_yh_data_lead", "沈星澜", "dept-data", "数据部", "数据负责人", "ou_yh_cto", ["星澜", "数据"]),
    _employee("emp-yh-014", "ou_yh_data_eng", "罗子墨", "dept-data", "数据部", "数据工程师", "ou_yh_data_lead", ["子墨", "数据工程"]),
    _employee("emp-yh-015", "ou_yh_ops_head", "韩舒雅", "dept-operations", "运营部", "运营总监", "ou_yh_ceo", ["舒雅", "运营"]),
    _employee("emp-yh-016", "ou_yh_release", "范景行", "dept-operations", "运营部", "发布经理", "ou_yh_ops_head", ["景行", "发布"]),
    _employee("emp-yh-017", "ou_yh_cfo", "宋知微", "dept-finance", "财务部", "CFO", "ou_yh_ceo", ["知微", "CFO"]),
    _employee("emp-yh-018", "ou_yh_finance_ops", "邵予怀", "dept-finance", "财务部", "财务运营经理", "ou_yh_cfo", ["予怀", "财务运营"]),
    _employee("emp-yh-019", "ou_yh_legal", "秦晚晴", "dept-legal", "法务部", "法务顾问", "ou_yh_ceo", ["晚晴", "法务"]),
    _employee("emp-yh-020", "ou_yh_marketing", "白芷晴", "dept-marketing", "市场部", "市场负责人", "ou_yh_cpo", ["芷晴", "市场"]),
    _employee("emp-yh-021", "ou_yh_cs_lead", "孟子昂", "dept-customer-success", "客户成功部", "客户成功负责人", "ou_yh_ceo", ["子昂", "客户成功"]),
    _employee("emp-yh-022", "ou_yh_support", "叶思源", "dept-customer-success", "客户成功部", "支持专员", "ou_yh_cs_lead", ["思源", "支持"]),
]

EMPLOYEE_BY_OPEN_ID_ZH = {employee["open_id"]: employee for employee in EMPLOYEES_ZH}

CHAT_LABELS_ZH = {
    "oc_yh_launch": "增长版发布作战群",
    "oc_yh_risk": "安全与法务评审群",
    "oc_yh_cutover": "数据迁移割接群",
    "oc_yh_incident": "支付回调 SEV-2 处置群",
    "oc_yh_finance": "财务审批协同群",
    "oc_yh_beta": "客户灰度升级群",
    "oc_yh_enablement": "发布物料与客服赋能群",
}

THREAD_LABELS_ZH = {
    "th_yh_launch": "Q2 增长版发布",
    "th_yh_risk": "安全与法务风险评审",
    "th_yh_cutover": "数仓 v2 割接",
    "th_yh_incident": "支付回调 SEV-2",
    "th_yh_finance": "预算与供应商审批",
    "th_yh_beta": "灰度客户升级",
    "th_yh_enablement": "发布赋能材料",
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


EVENT_SEEDS_ZH: list[EventSeed] = [
    EventSeed(1, 9, 0, "oc_yh_launch", "th_yh_launch", "ou_yh_cpo", "text", "Q2 增长版发布启动：PRD、风险评审、财务审批、灰度客户和客服赋能统一放在这条发布线里跟踪。", "launch_kickoff", ["ou_yh_product_pm", "ou_yh_eng_mgr", "ou_yh_marketing", "ou_yh_ops_head"], doc_refs=[_doc("doc:zh_prd_q2_growth", "Q2 增长版 PRD")], task_refs=[_task("PROD-510", status="planned", owner="ou_yh_product_pm")]),
    EventSeed(1, 9, 20, "oc_yh_launch", "th_yh_launch", "ou_yh_product_pm", "post", "PRD v0.9 已就绪。决策记录写的是 4 月 18 日发布，但前提是安全和财务都不阻塞。", "prd_v09", ["ou_yh_security_lead", "ou_yh_cfo"], doc_refs=[_doc("doc:zh_prd_q2_growth", "Q2 增长版 PRD")], task_refs=[_task("PROD-510", status="in_progress", owner="ou_yh_product_pm")]),
    EventSeed(1, 10, 5, "oc_yh_launch", "th_yh_launch", "ou_yh_eng_mgr", "text", "研发拆分：ENG-387 由昕然负责权益 API，一诺负责前端开关文案，昕然同时确认支付回调兼容性。", "eng_split", ["ou_yh_backend", "ou_yh_frontend"], task_refs=[_task("ENG-387", status="in_progress", owner="ou_yh_backend")]),
    EventSeed(1, 10, 40, "oc_yh_launch", "th_yh_launch", "ou_yh_design", "file", "已上传发布页红线稿，空状态文案还在引用旧的「增长实验室」名称。", "design_redlines", attachments=[_file("file:zh_launch_redlines_v1", "发布页红线稿_v1.fig")], task_refs=[_task("MKT-255", status="planned", owner="ou_yh_marketing")]),
    EventSeed(1, 11, 15, "oc_yh_risk", "th_yh_risk", "ou_yh_security_lead", "text", "创建 SEC-172 做 token scope 评审。在 SEC-172 关闭前，PROD-510 先按被安全阻塞处理。", "risk_open", ["ou_yh_product_pm", "ou_yh_seceng"], doc_refs=[_doc("doc:zh_risk_register", "Q2 发布风险登记表")], task_refs=[_task("SEC-172", status="open", owner="ou_yh_security_lead"), _task("PROD-510", status="blocked", owner="ou_yh_product_pm", blocked_by="SEC-172")]),
    EventSeed(1, 13, 0, "oc_yh_finance", "th_yh_finance", "ou_yh_finance_ops", "approval", "AP-824 已发起，覆盖功能开关超额费用和灰度客户支持额度。FIN-304 现在等待 AP-824。", "finance_open_ap824", ["ou_yh_cfo"], task_refs=[_task("FIN-304", status="pending_approval", owner="ou_yh_finance_ops", blocked_by="AP-824")], approval_refs=[_approval("AP-824", status="pending")]),
    EventSeed(1, 14, 25, "oc_yh_beta", "th_yh_beta", "ou_yh_cs_lead", "text", "星河制造和北辰零售都申请灰度资格，CS-431 跟踪客户名单和客服话术。", "beta_requests", ["ou_yh_product_pm", "ou_yh_support"], task_refs=[_task("CS-431", status="in_progress", owner="ou_yh_cs_lead")]),
    EventSeed(1, 15, 10, "oc_yh_enablement", "th_yh_enablement", "ou_yh_marketing", "post", "赋能材料初稿已放到 deck。它依赖最终发布日期和法务确认后的价格表述。", "enablement_draft", ["ou_yh_legal", "ou_yh_product_pm"], doc_refs=[_doc("doc:zh_enablement_plan", "Q2 发布赋能计划")], attachments=[_file("file:zh_enablement_deck_v1", "Q2发布赋能材料_v1.pptx")], task_refs=[_task("MKT-255", status="in_progress", owner="ou_yh_marketing", blocked_by="PROD-510")]),
    EventSeed(2, 9, 10, "oc_yh_cutover", "th_yh_cutover", "ou_yh_data_lead", "text", "DATA-218 今天开始：灰度分析迁到数仓 v2。割接执行人子墨，复核人知夏。", "cutover_start", ["ou_yh_data_eng", "ou_yh_sre"], doc_refs=[_doc("doc:zh_data_migration_plan", "数仓 v2 迁移方案")], task_refs=[_task("DATA-218", status="in_progress", owner="ou_yh_data_eng")]),
    EventSeed(2, 10, 0, "oc_yh_risk", "th_yh_risk", "ou_yh_seceng", "comment", "安全发现：一个 webhook scope 过宽。SEC-172 被 AP-810 阻塞，因为法务要先批准补偿控制说明。", "sec_blocked_by_ap810", ["ou_yh_legal"], doc_refs=[_doc("doc:zh_risk_register", "Q2 发布风险登记表")], task_refs=[_task("SEC-172", status="blocked", owner="ou_yh_security_lead", blocked_by="AP-810")], approval_refs=[_approval("AP-810", status="pending")]),
    EventSeed(2, 11, 30, "oc_yh_launch", "th_yh_launch", "ou_yh_product_pm", "text", "当前状态：PROD-510 仍然被阻塞，因为 SEC-172 在等 AP-810。不要对外宣布 4 月 18 日。", "launch_blocked_summary", ["ou_yh_marketing"], task_refs=[_task("PROD-510", status="blocked", owner="ou_yh_product_pm", blocked_by="SEC-172"), _task("SEC-172", status="blocked", owner="ou_yh_security_lead", blocked_by="AP-810")]),
    EventSeed(2, 13, 45, "oc_yh_incident", "th_yh_incident", "ou_yh_sre", "system", "监控创建 SEV-2：沙箱商户回放后支付回调重试数飙升，事故任务 OPS-199 已创建。", "incident_open", ["ou_yh_backend", "ou_yh_ops_head"], task_refs=[_task("OPS-199", status="open", owner="ou_yh_sre")], card_payload=_card("支付回调重试 SEV-2", "open", {"severity": "sev2"})),
    EventSeed(2, 14, 5, "oc_yh_incident", "th_yh_incident", "ou_yh_backend", "text", "一开始怀疑是功能开关判断，但链路追踪显示是重复 PSP callback id。ENG-387 不是根因。", "incident_not_flag", ["ou_yh_eng_mgr"], task_refs=[_task("ENG-387", status="in_progress", owner="ou_yh_backend"), _task("OPS-199", status="investigating", owner="ou_yh_sre")]),
    EventSeed(2, 16, 0, "oc_yh_finance", "th_yh_finance", "ou_yh_cfo", "approval", "AP-824 已批准，覆盖超额费用和支持额度。FIN-304 可以进入 ready。", "finance_ap824_approved", ["ou_yh_finance_ops"], task_refs=[_task("FIN-304", status="ready", owner="ou_yh_finance_ops")], approval_refs=[_approval("AP-824", status="approved", approved_by="ou_yh_cfo")]),
    EventSeed(3, 9, 0, "oc_yh_cutover", "th_yh_cutover", "ou_yh_data_eng", "text", "第一批回填完成，口径一致率 99.7%。DATA-218 还不能关闭，要等收入分群 join 对齐。", "cutover_batch1", ["ou_yh_data_lead"], task_refs=[_task("DATA-218", status="in_progress", owner="ou_yh_data_eng")]),
    EventSeed(3, 10, 15, "oc_yh_incident", "th_yh_incident", "ou_yh_sre", "text", "临时限流已上线。OPS-199 从 investigating 变为 mitigated，等待复盘和回放清理。", "incident_mitigated", ["ou_yh_release"], task_refs=[_task("OPS-199", status="mitigated", owner="ou_yh_sre")], doc_refs=[_doc("doc:zh_sev2_payment_postmortem", "支付回调 SEV-2 复盘")]),
    EventSeed(3, 11, 40, "oc_yh_beta", "th_yh_beta", "ou_yh_support", "text", "北辰零售反馈欢迎邮件还指向旧看板，我已写入 CS-431 备注。", "beta_beichen_email", ["ou_yh_marketing"], task_refs=[_task("CS-431", status="in_progress", owner="ou_yh_cs_lead")]),
    EventSeed(3, 14, 0, "oc_yh_risk", "th_yh_risk", "ou_yh_legal", "approval", "AP-810 已批准，条件是发布说明必须写明收窄后的 token scope。SEC-172 可以恢复推进。", "ap810_approved", ["ou_yh_security_lead"], approval_refs=[_approval("AP-810", status="approved", approved_by="ou_yh_legal")], task_refs=[_task("SEC-172", status="in_progress", owner="ou_yh_security_lead")]),
    EventSeed(3, 15, 20, "oc_yh_launch", "th_yh_launch", "ou_yh_product_pm", "text", "法务批准后更新：PROD-510 不再直接受 AP-810 阻塞，但还要等安琪关闭 SEC-172。", "prod_waits_sec_close", ["ou_yh_security_lead", "ou_yh_marketing"], task_refs=[_task("PROD-510", status="blocked", owner="ou_yh_product_pm", blocked_by="SEC-172")]),
    EventSeed(4, 9, 30, "oc_yh_risk", "th_yh_risk", "ou_yh_security_lead", "text", "SEC-172 已关闭。token scope 说明已经写进风险登记表和发布说明，PROD-510 的安全阻塞解除。", "sec172_closed", ["ou_yh_product_pm"], doc_refs=[_doc("doc:zh_risk_register", "Q2 发布风险登记表")], task_refs=[_task("SEC-172", status="done", owner="ou_yh_security_lead"), _task("PROD-510", status="in_progress", owner="ou_yh_product_pm")]),
    EventSeed(4, 10, 10, "oc_yh_launch", "th_yh_launch", "ou_yh_cpo", "text", "决策：发布日期从 4 月 18 日调整到 4 月 22 日，因为 DATA-218 口径校验和赋能材料还需要一轮。", "launch_date_moved", ["ou_yh_marketing", "ou_yh_ops_head"], task_refs=[_task("PROD-510", status="in_progress", owner="ou_yh_product_pm"), _task("DATA-218", status="in_progress", owner="ou_yh_data_eng")], relations=[_rel("blocked_by", "task:MKT-255", "task:PROD-510")]),
    EventSeed(4, 13, 0, "oc_yh_enablement", "th_yh_enablement", "ou_yh_marketing", "text", "赋能 deck 必须写 4 月 22 日，不要再写 4 月 18 日。我在更新 MKT-255 和客户 FAQ。", "enablement_date_change", ["ou_yh_support"], attachments=[_file("file:zh_enablement_deck_v2", "Q2发布赋能材料_v2.pptx")], task_refs=[_task("MKT-255", status="in_progress", owner="ou_yh_marketing", blocked_by="PROD-510")]),
    EventSeed(4, 16, 15, "oc_yh_cutover", "th_yh_cutover", "ou_yh_sre", "comment", "知夏复核：割接 runbook 还缺回滚 owner，DATA-218 暂时不能标 ready。", "cutover_needs_rollback", ["ou_yh_data_eng", "ou_yh_release"], doc_refs=[_doc("doc:zh_data_migration_plan", "数仓 v2 迁移方案")], task_refs=[_task("DATA-218", status="blocked", owner="ou_yh_data_eng", blocked_by="OPS-199")]),
    EventSeed(5, 9, 10, "oc_yh_incident", "th_yh_incident", "ou_yh_release", "post", "复盘初稿确认是重复 PSP callback id 导致峰值。景行负责回放清理，知夏负责监控阈值更新。", "postmortem_owner_split", ["ou_yh_sre"], doc_refs=[_doc("doc:zh_sev2_payment_postmortem", "支付回调 SEV-2 复盘")], task_refs=[_task("OPS-199", status="in_progress", owner="ou_yh_release")]),
    EventSeed(5, 11, 30, "oc_yh_cutover", "th_yh_cutover", "ou_yh_data_lead", "text", "负责人变更：DATA-218 最终割接决策由子墨转给星澜，因为子墨要参与回放清理值班。", "data_owner_change", ["ou_yh_data_eng", "ou_yh_sre"], task_refs=[_task("DATA-218", status="in_progress", owner="ou_yh_data_lead")]),
    EventSeed(5, 14, 0, "oc_yh_beta", "th_yh_beta", "ou_yh_cs_lead", "text", "星河制造可在 4 月 22 日后进入灰度；北辰零售仍被旧看板邮件文案阻塞，关联 MKT-255。", "beta_split_status", ["ou_yh_marketing"], task_refs=[_task("CS-431", status="in_progress", owner="ou_yh_cs_lead"), _task("MKT-255", status="in_progress", owner="ou_yh_marketing", blocked_by="PROD-510")]),
    EventSeed(6, 9, 20, "oc_yh_finance", "th_yh_finance", "ou_yh_finance_ops", "text", "财务 PO 已覆盖，FIN-304 done；发布没有剩余预算阻塞。", "fin304_done", ["ou_yh_product_pm"], task_refs=[_task("FIN-304", status="done", owner="ou_yh_finance_ops")]),
    EventSeed(6, 10, 5, "oc_yh_incident", "th_yh_incident", "ou_yh_sre", "text", "回放清理完成。OPS-199 已关闭，不再阻塞 DATA-218 的回滚方案。", "ops199_closed", ["ou_yh_data_lead"], task_refs=[_task("OPS-199", status="done", owner="ou_yh_release"), _task("DATA-218", status="in_progress", owner="ou_yh_data_lead")]),
    EventSeed(6, 13, 35, "oc_yh_cutover", "th_yh_cutover", "ou_yh_data_lead", "text", "DATA-218 ready。回滚 owner 是知夏，go/no-go owner 是星澜，口径一致率达到 99.95%。", "data218_ready", ["ou_yh_sre", "ou_yh_release"], task_refs=[_task("DATA-218", status="ready", owner="ou_yh_data_lead")]),
    EventSeed(7, 9, 0, "oc_yh_launch", "th_yh_launch", "ou_yh_product_pm", "text", "发布检查清单 v1：安全完成、财务完成、数据 ready、事故关闭。剩余阻塞是 MKT-255 客户文案和 AP-831 法务审批。", "launch_checklist_v1", ["ou_yh_marketing", "ou_yh_legal"], doc_refs=[_doc("doc:zh_launch_checklist", "Q2 发布检查清单")], task_refs=[_task("PROD-510", status="ready", owner="ou_yh_product_pm"), _task("MKT-255", status="blocked", owner="ou_yh_marketing", blocked_by="AP-831")], approval_refs=[_approval("AP-831", status="pending")]),
    EventSeed(7, 10, 20, "oc_yh_enablement", "th_yh_enablement", "ou_yh_legal", "comment", "AP-831 法务意见：把「保证提升转化」改成「灰度客户中观察到转化提升」后才能批准。", "ap831_requested_change", ["ou_yh_marketing"], doc_refs=[_doc("doc:zh_customer_faq", "客户 FAQ")], approval_refs=[_approval("AP-831", status="changes_requested")], task_refs=[_task("MKT-255", status="blocked", owner="ou_yh_marketing", blocked_by="AP-831")]),
    EventSeed(7, 13, 30, "oc_yh_enablement", "th_yh_enablement", "ou_yh_marketing", "text", "已按晚晴意见更新 FAQ 和 deck：统一使用「灰度客户中观察到转化提升」。AP-831 可以复审。", "marketing_revised_copy", ["ou_yh_legal"], attachments=[_file("file:zh_enablement_deck_v3", "Q2发布赋能材料_v3.pptx")], doc_refs=[_doc("doc:zh_customer_faq", "客户 FAQ")], task_refs=[_task("MKT-255", status="review", owner="ou_yh_marketing", blocked_by="AP-831")], approval_refs=[_approval("AP-831", status="pending")]),
    EventSeed(8, 9, 45, "oc_yh_enablement", "th_yh_enablement", "ou_yh_legal", "approval", "AP-831 已批准。批准话术是「灰度客户中观察到转化提升」。MKT-255 等客户成功确认后即可关闭。", "ap831_approved", ["ou_yh_marketing", "ou_yh_cs_lead"], approval_refs=[_approval("AP-831", status="approved", approved_by="ou_yh_legal")], task_refs=[_task("MKT-255", status="in_progress", owner="ou_yh_marketing")]),
    EventSeed(8, 11, 0, "oc_yh_beta", "th_yh_beta", "ou_yh_support", "text", "客户成功确认星河制造和北辰零售的话术都可用。CS-431 等发布邮件发出后关闭。", "cs_signoff", ["ou_yh_marketing"], task_refs=[_task("CS-431", status="ready", owner="ou_yh_cs_lead"), _task("MKT-255", status="in_progress", owner="ou_yh_marketing")]),
    EventSeed(8, 15, 15, "oc_yh_launch", "th_yh_launch", "ou_yh_cpo", "card", "发布 readiness 卡片：所有主阻塞已清除。最终 go/no-go 时间仍是 4 月 21 日 16:00。", "readiness_card_all_clear", ["ou_yh_ceo"], task_refs=[_task("PROD-510", status="ready", owner="ou_yh_product_pm"), _task("DATA-218", status="ready", owner="ou_yh_data_lead"), _task("FIN-304", status="done", owner="ou_yh_finance_ops"), _task("MKT-255", status="in_progress", owner="ou_yh_marketing")], card_payload=_card("Q2 增长版发布 readiness", "green", {"go_no_go": "2026-04-21T16:00:00+08:00"})),
    EventSeed(9, 9, 30, "oc_yh_enablement", "th_yh_enablement", "ou_yh_marketing", "text", "MKT-255 已关闭。deck v3 和 FAQ 均已批准，客服话术已挂到赋能计划里。", "mkt255_done", ["ou_yh_cs_lead"], doc_refs=[_doc("doc:zh_enablement_plan", "Q2 发布赋能计划"), _doc("doc:zh_customer_faq", "客户 FAQ")], attachments=[_file("file:zh_enablement_deck_v3", "Q2发布赋能材料_v3.pptx")], task_refs=[_task("MKT-255", status="done", owner="ou_yh_marketing")]),
    EventSeed(9, 13, 0, "oc_yh_beta", "th_yh_beta", "ou_yh_cs_lead", "text", "CS-431 已关闭。星河制造和北辰零售都被标记为 4 月 22 日发布邮件对象，思源负责首轮响应。", "cs431_done", ["ou_yh_support"], task_refs=[_task("CS-431", status="done", owner="ou_yh_cs_lead")]),
    EventSeed(10, 9, 0, "oc_yh_launch", "th_yh_launch", "ou_yh_ops_head", "text", "运营检查：发布日期仍是 4 月 22 日。景行负责发布命令，舒雅负责管理层同步。", "ops_launch_check", ["ou_yh_release", "ou_yh_ceo"], task_refs=[_task("PROD-510", status="ready", owner="ou_yh_product_pm")]),
    EventSeed(10, 10, 30, "oc_yh_launch", "th_yh_launch", "ou_yh_ceo", "text", "管理层 go/no-go：批准 4 月 22 日发布，条件是发布窗口前不能出现新的 SEV-1 或安全阻塞。", "exec_go", ["ou_yh_cpo", "ou_yh_cto", "ou_yh_ops_head"], task_refs=[_task("PROD-510", status="approved", owner="ou_yh_product_pm")]),
    EventSeed(10, 16, 0, "oc_yh_launch", "th_yh_launch", "ou_yh_release", "system", "发布窗口已排期：4 月 22 日 09:00。回滚 owner 知夏，发布 PM 雨薇，对外沟通芷晴。", "release_window_scheduled", ["ou_yh_sre", "ou_yh_product_pm", "ou_yh_marketing"], task_refs=[_task("PROD-510", status="scheduled", owner="ou_yh_product_pm"), _task("DATA-218", status="scheduled", owner="ou_yh_data_lead")]),
    EventSeed(11, 9, 0, "oc_yh_cutover", "th_yh_cutover", "ou_yh_data_lead", "system", "数仓 v2 割接开始。DATA-218 进入发布窗口，旧看板导出改为只读。", "cutover_started", ["ou_yh_sre"], task_refs=[_task("DATA-218", status="deploying", owner="ou_yh_data_lead")], card_payload=_card("数仓 v2 割接", "deploying")),
    EventSeed(11, 9, 30, "oc_yh_launch", "th_yh_launch", "ou_yh_release", "system", "Q2 增长版发布开始，功能开关先放量到 10% 灰度客户。", "launch_started", ["ou_yh_product_pm", "ou_yh_backend"], task_refs=[_task("PROD-510", status="deploying", owner="ou_yh_product_pm")], card_payload=_card("Q2 增长版发布", "deploying", {"flag": "10%"})),
    EventSeed(11, 10, 15, "oc_yh_incident", "th_yh_incident", "ou_yh_sre", "text", "发布期间支付回调监控安静，之前 SEV-2 的修复保持稳定。", "incident_monitor_quiet", ["ou_yh_release"], task_refs=[_task("OPS-199", status="done", owner="ou_yh_release")]),
    EventSeed(11, 11, 45, "oc_yh_launch", "th_yh_launch", "ou_yh_backend", "text", "权益 API 在 50% 放量下稳定，没有重复 callback 回归。ENG-387 等 100% 后可关闭。", "eng387_steady", ["ou_yh_eng_mgr"], task_refs=[_task("ENG-387", status="verifying", owner="ou_yh_backend")]),
    EventSeed(11, 13, 15, "oc_yh_cutover", "th_yh_cutover", "ou_yh_data_eng", "text", "数仓 v2 在真实流量下口径一致率 99.98%，无需回滚。", "cutover_live_parity", ["ou_yh_data_lead"], task_refs=[_task("DATA-218", status="verifying", owner="ou_yh_data_lead")]),
    EventSeed(11, 15, 40, "oc_yh_launch", "th_yh_launch", "ou_yh_release", "system", "功能开关达到 100%。PROD-510 发布完成。", "prod510_complete", ["ou_yh_cpo"], task_refs=[_task("PROD-510", status="done", owner="ou_yh_product_pm")], card_payload=_card("Q2 增长版发布", "complete", {"flag": "100%"})),
    EventSeed(12, 9, 20, "oc_yh_cutover", "th_yh_cutover", "ou_yh_data_lead", "text", "DATA-218 已关闭。从今天起，数仓 v2 看板是灰度分析的唯一口径。", "data218_done", ["ou_yh_cpo"], task_refs=[_task("DATA-218", status="done", owner="ou_yh_data_lead")]),
    EventSeed(12, 10, 10, "oc_yh_launch", "th_yh_launch", "ou_yh_eng_mgr", "text", "ENG-387 done。昕然已把支付回调兼容说明写进发布 runbook。", "eng387_done", ["ou_yh_backend"], doc_refs=[_doc("doc:zh_launch_runbook", "Q2 发布 Runbook")], task_refs=[_task("ENG-387", status="done", owner="ou_yh_backend")]),
    EventSeed(12, 11, 30, "oc_yh_beta", "th_yh_beta", "ou_yh_support", "text", "星河制造反馈积极；北辰零售仍需要 SSO 映射协助，但这是发布后的支持事项，不是发布阻塞。", "post_launch_beta_support", ["ou_yh_cs_lead"], task_refs=[_task("CS-431", status="done", owner="ou_yh_cs_lead")]),
    EventSeed(12, 14, 0, "oc_yh_launch", "th_yh_launch", "ou_yh_cpo", "post", "最终发布状态：PROD-510、ENG-387、DATA-218、FIN-304、MKT-255、CS-431、SEC-172、OPS-199 全部 done。发布日期是 4 月 22 日。", "final_launch_status", ["ou_yh_ceo"], doc_refs=[_doc("doc:zh_launch_checklist", "Q2 发布检查清单")], task_refs=[_task("PROD-510", status="done", owner="ou_yh_product_pm"), _task("ENG-387", status="done", owner="ou_yh_backend"), _task("DATA-218", status="done", owner="ou_yh_data_lead"), _task("FIN-304", status="done", owner="ou_yh_finance_ops"), _task("MKT-255", status="done", owner="ou_yh_marketing"), _task("CS-431", status="done", owner="ou_yh_cs_lead"), _task("SEC-172", status="done", owner="ou_yh_security_lead"), _task("OPS-199", status="done", owner="ou_yh_release")]),
]


def _status_by_day(day: int, *, early: str, middle: str, late: str, done: str = "done") -> str:
    if day <= 3:
        return early
    if day <= 7:
        return middle
    if day <= 10:
        return late
    return done


def _supporting_event_seeds_zh() -> list[EventSeed]:
    seeds: list[EventSeed] = []
    for day in range(1, 13):
        status = _status_by_day(day, early="in_progress", middle="blocked", late="ready")
        if day >= 11:
            status = "deploying" if day == 11 else "done"
        seeds.append(
            EventSeed(
                day,
                8,
                45,
                "oc_yh_launch",
                "th_yh_launch",
                "ou_yh_product_pm" if day % 2 else "ou_yh_release",
                "bot_notice" if day == 11 else "text",
                f"发布晨会第 {day} 天：PROD-510 当前为 {status}，安全、数据、财务、赋能和客户成功依赖未确认前不要改外部口径。",
                mentions=["ou_yh_marketing", "ou_yh_ops_head"],
                doc_refs=[_doc("doc:zh_launch_checklist", "Q2 发布检查清单")],
                task_refs=[_task("PROD-510", status=status, owner="ou_yh_product_pm")],
            )
        )
    for day in range(1, 9):
        status = "blocked" if day in {2, 3} else ("done" if day >= 4 else "open")
        seeds.append(
            EventSeed(
                day,
                12,
                10,
                "oc_yh_risk",
                "th_yh_risk",
                "ou_yh_security_lead" if day % 2 else "ou_yh_seceng",
                "document" if day == 4 else "comment",
                f"风险同步第 {day} 天：SEC-172 状态为 {status}，token scope 说明必须留在风险登记表，不能沿用过期发布日期。",
                mentions=["ou_yh_product_pm"],
                doc_refs=[_doc("doc:zh_risk_register", "Q2 发布风险登记表")],
                task_refs=[_task("SEC-172", status=status, owner="ou_yh_security_lead")],
            )
        )
    for day in range(2, 13):
        owner = "ou_yh_data_eng" if day < 5 else "ou_yh_data_lead"
        status = _status_by_day(day, early="in_progress", middle="blocked", late="ready")
        if day >= 11:
            status = "deploying" if day == 11 else "done"
        seeds.append(
            EventSeed(
                day,
                12,
                25,
                "oc_yh_cutover",
                "th_yh_cutover",
                owner,
                "text",
                f"数据割接同步第 {day} 天：DATA-218 为 {status}，口径一致率、回滚 owner 和看板口径都记录在迁移方案。",
                mentions=["ou_yh_sre"],
                doc_refs=[_doc("doc:zh_data_migration_plan", "数仓 v2 迁移方案")],
                task_refs=[_task("DATA-218", status=status, owner=owner)],
            )
        )
    for day in range(1, 10):
        status = "blocked" if day in {4, 7} else ("done" if day == 9 else "in_progress")
        seeds.append(
            EventSeed(
                day,
                16,
                30,
                "oc_yh_enablement",
                "th_yh_enablement",
                "ou_yh_marketing",
                "document" if day == 7 else "text",
                f"赋能材料同步第 {day} 天：MKT-255 为 {status}，deck、FAQ 和客服话术必须跟随最新发布日期和法务表述。",
                mentions=["ou_yh_cs_lead", "ou_yh_legal"],
                doc_refs=[_doc("doc:zh_enablement_plan", "Q2 发布赋能计划")],
                task_refs=[_task("MKT-255", status=status, owner="ou_yh_marketing")],
            )
        )
    for day in range(1, 13):
        status = "done" if day >= 9 else ("ready" if day == 8 else "in_progress")
        seeds.append(
            EventSeed(
                day,
                16,
                45,
                "oc_yh_beta",
                "th_yh_beta",
                "ou_yh_cs_lead" if day % 2 else "ou_yh_support",
                "text",
                f"灰度客户同步第 {day} 天：CS-431 为 {status}，星河制造和北辰零售的问题统一走客服话术，不要私下承诺发布时间。",
                mentions=["ou_yh_marketing"],
                task_refs=[_task("CS-431", status=status, owner="ou_yh_cs_lead")],
            )
        )
    return seeds


def _all_event_seeds_zh() -> list[EventSeed]:
    return sorted(
        [*EVENT_SEEDS_ZH, *_supporting_event_seeds_zh()],
        key=lambda seed: (seed.day, seed.hour, seed.minute, seed.chat_id, seed.thread_id, seed.sender_open_id),
    )


def _event_time(seed: EventSeed) -> str:
    start = datetime(2026, 4, 1, tzinfo=timezone.utc)
    value = start + timedelta(days=seed.day - 1, hours=seed.hour, minutes=seed.minute)
    return value.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_yunhe_q2_ops_zh_events(
    snapshot_id: str = YUNHE_Q2_OPS_ZH_SNAPSHOT_ID,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    events: list[dict[str, Any]] = []
    event_id_by_key: dict[str, str] = {}
    thread_root_message_id: dict[str, str] = {}
    for index, seed in enumerate(_all_event_seeds_zh(), start=1):
        event_id = f"evt_yh_q2_zh_{index:04d}"
        message_id = f"om_yh_q2_zh_{index:04d}"
        reply_to_message_id = thread_root_message_id.get(seed.thread_id, "")
        thread_root_message_id.setdefault(seed.thread_id, message_id)
        if seed.key:
            event_id_by_key[seed.key] = event_id
        employee = EMPLOYEE_BY_OPEN_ID_ZH[seed.sender_open_id]
        events.append(
            normalize_office_event(
                {
                    "event_id": event_id,
                    "snapshot_id": snapshot_id,
                    "workspace_id": YUNHE_WORKSPACE_ID,
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
                        "source": "deterministic_chinese_fixture",
                        "chat_label": CHAT_LABELS_ZH[seed.chat_id],
                        "thread_label": THREAD_LABELS_ZH[seed.thread_id],
                        "seed_key": seed.key,
                    },
                    "direction": "inbound",
                    "chat_type": "group",
                    "entity_refs": [
                        {"id": f"chat:{seed.chat_id}", "label": CHAT_LABELS_ZH[seed.chat_id]},
                        {"id": f"thread:{seed.thread_id}", "label": THREAD_LABELS_ZH[seed.thread_id]},
                    ],
                    "relations": seed.relations,
                },
                snapshot_id=snapshot_id,
            )
        )
    return events, event_id_by_key


def _history_window(*, chat_ids: list[str] | None = None) -> dict[str, Any]:
    return {
        "event_ids": [],
        "start_time": "2026-04-01T09:00:00Z",
        "end_time": "2026-04-12T14:00:00Z",
        "chat_ids": chat_ids or [],
        "thread_ids": [],
        "max_events": 120,
    }


def build_yunhe_q2_ops_zh_validation_manifest(
    event_id_by_key: dict[str, str],
    *,
    snapshot_id: str = YUNHE_Q2_OPS_ZH_SNAPSHOT_ID,
) -> dict[str, Any]:
    def ids(*keys: str) -> list[str]:
        return [event_id_by_key[key] for key in keys]

    cases = [
        {
            "case_id": "yunhe-zh-001-final-launch-status",
            "history_window": _history_window(chat_ids=["oc_yh_launch"]),
            "question": "Q2 增长版最终发布状态是什么？哪些关键工作流已完成？",
            "expected_answer": "Q2 增长版在 4 月 22 日完成发布，PROD-510、ENG-387、DATA-218、FIN-304、MKT-255、CS-431、SEC-172、OPS-199 全部 done。",
            "evidence_event_ids": ids("prod510_complete", "final_launch_status"),
            "ability_tag": "long_horizon_status",
        },
        {
            "case_id": "yunhe-zh-002-security-block-chain",
            "history_window": _history_window(chat_ids=["oc_yh_launch", "oc_yh_risk"]),
            "question": "PROD-510 早期被阻塞的完整链路是什么？",
            "expected_answer": "PROD-510 被 SEC-172 阻塞，SEC-172 又被 AP-810 阻塞，直到法务批准 AP-810。",
            "evidence_event_ids": ids("risk_open", "sec_blocked_by_ap810", "ap810_approved", "sec172_closed"),
            "ability_tag": "blocked_by_chain",
        },
        {
            "case_id": "yunhe-zh-003-data-owner-change",
            "history_window": _history_window(chat_ids=["oc_yh_cutover", "oc_yh_incident"]),
            "question": "DATA-218 最终割接决策由谁负责？为什么换负责人？",
            "expected_answer": "DATA-218 最终割接决策由沈星澜负责，因为罗子墨要参与回放清理值班。",
            "evidence_event_ids": ids("data_owner_change", "data218_ready", "data218_done"),
            "ability_tag": "owner_change",
        },
        {
            "case_id": "yunhe-zh-004-incident-root-cause",
            "history_window": _history_window(chat_ids=["oc_yh_incident", "oc_yh_launch"]),
            "question": "ENG-387 是支付回调 SEV-2 的根因吗？",
            "expected_answer": "不是。功能开关判断的初始怀疑被排除，根因是重复 PSP callback id。",
            "evidence_event_ids": ids("incident_not_flag", "postmortem_owner_split"),
            "ability_tag": "stale_info_resolution",
        },
        {
            "case_id": "yunhe-zh-005-finance-approval",
            "history_window": _history_window(chat_ids=["oc_yh_finance", "oc_yh_launch"]),
            "question": "AP-824 最终如何处理？财务是否还阻塞发布？",
            "expected_answer": "AP-824 由宋知微批准，FIN-304 先进入 ready 后完成，因此财务不再阻塞发布。",
            "evidence_event_ids": ids("finance_open_ap824", "finance_ap824_approved", "fin304_done"),
            "ability_tag": "approval_progression",
        },
        {
            "case_id": "yunhe-zh-006-legal-copy",
            "history_window": _history_window(chat_ids=["oc_yh_enablement"]),
            "question": "法务最终批准的客户侧转化提升话术是什么？",
            "expected_answer": "法务批准的话术是「灰度客户中观察到转化提升」。",
            "evidence_event_ids": ids("ap831_requested_change", "marketing_revised_copy", "ap831_approved"),
            "ability_tag": "doc_reference",
        },
        {
            "case_id": "yunhe-zh-007-launch-date",
            "history_window": _history_window(chat_ids=["oc_yh_launch", "oc_yh_enablement"]),
            "question": "最终发布日期是哪天？哪个旧日期应该忽略？",
            "expected_answer": "最终发布日期是 4 月 22 日，早期的 4 月 18 日目标应该忽略。",
            "evidence_event_ids": ids("prd_v09", "launch_date_moved", "ops_launch_check", "final_launch_status"),
            "ability_tag": "temporal_reasoning",
        },
        {
            "case_id": "yunhe-zh-008-enable-deck-file",
            "history_window": _history_window(chat_ids=["oc_yh_enablement"]),
            "question": "最终获批的赋能 deck 是哪个版本？",
            "expected_answer": "最终获批的赋能 deck 是 Q2发布赋能材料_v3.pptx。",
            "evidence_event_ids": ids("marketing_revised_copy", "mkt255_done"),
            "ability_tag": "file_reference",
        },
        {
            "case_id": "yunhe-zh-009-beta-customers",
            "history_window": _history_window(chat_ids=["oc_yh_beta", "oc_yh_enablement"]),
            "question": "星河制造和北辰零售的灰度沟通最后如何处理？",
            "expected_answer": "CS-431 已关闭，星河制造和北辰零售都被标记为 4 月 22 日发布邮件对象，叶思源负责首轮响应。",
            "evidence_event_ids": ids("beta_requests", "beta_split_status", "cs431_done"),
            "ability_tag": "cross_thread_relation",
        },
        {
            "case_id": "yunhe-zh-010-data-cutover-readiness",
            "history_window": _history_window(chat_ids=["oc_yh_cutover", "oc_yh_incident"]),
            "question": "DATA-218 从被回滚方案阻塞到 ready 的关键条件是什么？",
            "expected_answer": "OPS-199 回放清理关闭，回滚 owner 知夏已明确，星澜负责 go/no-go，口径一致率达到 99.95%。",
            "evidence_event_ids": ids("cutover_needs_rollback", "ops199_closed", "data218_ready"),
            "ability_tag": "blocked_by_chain",
        },
        {
            "case_id": "yunhe-zh-011-go-no-go",
            "history_window": _history_window(chat_ids=["oc_yh_launch"]),
            "question": "谁批准了管理层 go/no-go？附带条件是什么？",
            "expected_answer": "林若安批准 4 月 22 日发布，条件是发布窗口前不能出现新的 SEV-1 或安全阻塞。",
            "evidence_event_ids": ids("exec_go", "release_window_scheduled"),
            "ability_tag": "approval_progression",
        },
        {
            "case_id": "yunhe-zh-012-ops-release-roles",
            "history_window": _history_window(chat_ids=["oc_yh_launch"]),
            "question": "发布窗口里回滚、发布 PM 和对外沟通分别是谁负责？",
            "expected_answer": "何知夏负责回滚，陈雨薇是发布 PM，白芷晴负责对外沟通。",
            "evidence_event_ids": ids("release_window_scheduled"),
            "ability_tag": "multi_party_dependency",
        },
        {
            "case_id": "yunhe-zh-013-security-final",
            "history_window": _history_window(chat_ids=["oc_yh_risk", "oc_yh_launch"]),
            "question": "SEC-172 最终状态是什么？token scope 说明记录在哪里？",
            "expected_answer": "SEC-172 最终 done，token scope 说明记录在风险登记表和发布说明里。",
            "evidence_event_ids": ids("ap810_approved", "sec172_closed", "final_launch_status"),
            "ability_tag": "doc_reference",
        },
        {
            "case_id": "yunhe-zh-014-graph-owner-status",
            "history_window": _history_window(),
            "question": "Graph 应该把 PROD-510、DATA-218、MKT-255、FIN-304 分别连到哪些最终负责人？",
            "expected_answer": "PROD-510 连到陈雨薇，DATA-218 连到沈星澜，MKT-255 连到白芷晴，FIN-304 连到邵予怀。",
            "evidence_event_ids": ids("final_launch_status", "data_owner_change", "mkt255_done", "fin304_done"),
            "ability_tag": "graph_hit",
        },
    ]
    return {
        "snapshot_id": snapshot_id,
        "description": "云河 Q2 中文办公 fixture snapshot 的只读验证清单。",
        "cases": [normalize_validation_case(case, snapshot_id=snapshot_id) for case in cases],
    }


def _metadata(snapshot_id: str, employees: list[dict[str, Any]], events: list[dict[str, Any]], cases: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "snapshot_id": snapshot_id,
        "source": "deterministic_realistic_enterprise_fixture_zh",
        "workspace_id": YUNHE_WORKSPACE_ID,
        "created_at": "2026-04-25T00:00:00Z",
        "frozen_at": "2026-04-25T00:00:00Z",
        "scenario": "一家中文 B2B SaaS 公司在 Q2 增长版发布期间的产品、研发、安全、数据、财务、法务、市场和客户成功协作。",
        "employees_version": {
            "employee_count": len(employees),
            "source": "eval.office_fixture_dataset_zh.EMPLOYEES_ZH",
        },
        "validation_case_count": len(cases),
        "coverage": {
            "chats": CHAT_LABELS_ZH,
            "threads": THREAD_LABELS_ZH,
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
            "policy": "不要原地修改该 snapshot；更新或真实 Feishu 回流应创建新的 snapshot_id。",
            "validation_mode": "read_only_replay",
        },
    }


def write_yunhe_q2_ops_zh_snapshot(
    *,
    root_dir: str | Path = "eval/office_dataset",
    snapshot_id: str = YUNHE_Q2_OPS_ZH_SNAPSHOT_ID,
) -> Path:
    root = Path(root_dir)
    snapshot_dir = root / "snapshots" / snapshot_id
    if snapshot_dir.exists():
        raise FileExistsError(f"Snapshot already exists and is immutable: {snapshot_dir}")

    snapshot_dir.mkdir(parents=True, exist_ok=False)
    employees = sorted(EMPLOYEES_ZH, key=lambda item: item["employee_id"])
    events, event_id_by_key = build_yunhe_q2_ops_zh_events(snapshot_id=snapshot_id)
    manifest = build_yunhe_q2_ops_zh_validation_manifest(event_id_by_key, snapshot_id=snapshot_id)

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
