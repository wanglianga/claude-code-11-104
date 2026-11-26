"""ORM -> API dict。前端直接消费这些结构。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from .models import (
    CommandReceipt,
    Credential,
    NetworkCommand,
    PhoneNumber,
    ReplaceOrder,
    SimCard,
    TaskItem,
)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat(sep=" ") if dt else None


def user_brief(u) -> dict:
    return {"id": u.id, "username": u.username, "display_name": u.display_name,
            "role": u.role, "contact": u.contact, "customer_id": u.customer_id}


def _customer_brief(db: Session, customer_id: int) -> dict | None:
    from .models import Customer
    c = db.get(Customer, customer_id)
    if c is None:
        return None
    return {"id": c.id, "name": c.name, "id_type": c.id_type, "id_number": c.id_number}


def plan_dict(p) -> dict:
    return {"id": p.id, "code": p.code, "name": p.name, "data_mb": p.data_mb,
            "voice_min": p.voice_min, "permissions": p.permissions or [],
            "monthly_fee": p.monthly_fee, "version": p.version}


def number_dict(n: PhoneNumber, db: Session | None = None) -> dict:
    return {
        "id": n.id, "msisdn": n.msisdn, "customer_id": n.customer_id,
        "plan_id": n.plan_id, "plan": plan_dict(n.plan) if n.plan else None,
        "plan_version": n.plan_version, "billing_cycle_day": n.billing_cycle_day,
        "service_status": n.service_status,
        "cycle_data_used_mb": n.cycle_data_used_mb,
        "cycle_voice_used_min": n.cycle_voice_used_min,
        "benefits_used_count": n.benefits_used_count,
    }


def card_dict(c: SimCard) -> dict:
    return {"id": c.id, "iccid": c.iccid, "card_no": c.card_no,
            "form_factor": c.form_factor, "network_gen": c.network_gen,
            "profile_type": c.profile_type, "status": c.status,
            "reserved_order_id": c.reserved_order_id, "stock_batch": c.stock_batch}


def credential_dict(c: Credential | None) -> dict | None:
    if c is None:
        return None
    return {
        "id": c.id, "credential_code": c.credential_code, "number_id": c.number_id,
        "card_id": c.card_id, "order_id": c.order_id, "status": c.status,
        "profile_snapshot": c.profile_snapshot or {},
        "profile_plan_version": c.profile_plan_version, "profile_stale": c.profile_stale,
        "original_enable_command_id": c.original_enable_command_id,
        "created_at_sim": iso(c.created_at_sim), "prepared_at_sim": iso(c.prepared_at_sim),
        "activated_at_sim": iso(c.activated_at_sim), "stopped_at_sim": iso(c.stopped_at_sim),
    }


def command_dict(c: NetworkCommand) -> dict:
    return {
        "id": c.id, "command_no": c.command_no, "order_id": c.order_id,
        "number_id": c.number_id, "credential_id": c.credential_id,
        "relates_to_id": c.relates_to_id, "kind": c.kind, "status": c.status,
        "request_payload": c.request_payload or {},
        "response_code": c.response_code, "response_message": c.response_message,
        "fault_mode": c.fault_mode, "duration_min": c.duration_min, "attempt": c.attempt,
        "queued_at_sim": iso(c.queued_at_sim), "sent_at_sim": iso(c.sent_at_sim),
        "estimated_complete_at_sim": iso(c.estimated_complete_at_sim),
        "due_at_sim": iso(c.due_at_sim), "unknown_at_sim": iso(c.unknown_at_sim),
        "completed_at_sim": iso(c.completed_at_sim),
        "adapter_executed_at_sim": iso(c.adapter_executed_at_sim),
        "adapter_outcome": c.adapter_outcome,
    }


def receipt_dict(r: CommandReceipt) -> dict:
    return {"id": r.id, "receipt_no": r.receipt_no, "command_no": r.command_no,
            "original_command_no": r.original_command_no, "outcome": r.outcome,
            "code": r.code, "message": r.message, "raw": r.raw or {},
            "received_at_sim": iso(r.received_at_sim), "applied": r.applied,
            "ignore_reason": r.ignore_reason}


def task_dict(t: TaskItem) -> dict:
    return {"id": t.id, "order_id": t.order_id, "assignee_role": t.assignee_role,
            "type": t.type, "title": t.title, "detail": t.detail, "status": t.status,
            "action_hint": t.action_hint, "created_at_sim": iso(t.created_at_sim),
            "done_at_sim": iso(t.done_at_sim)}


def order_brief(o: ReplaceOrder, db: Session) -> dict:
    n = db.get(PhoneNumber, o.number_id)
    return {
        "id": o.id, "order_no": o.order_no, "number_id": o.number_id,
        "msisdn": n.msisdn if n else None, "customer_id": o.customer_id,
        "reason": o.reason, "strategy": o.strategy, "status": o.status,
        "old_card_in_hand": o.old_card_in_hand,
        "assigned_card_id": o.assigned_card_id,
        "created_at": o.created_at.isoformat(sep=" ") if o.created_at else None,
        "t0_sim": iso(o.t0_sim),
        "outage_start_planned_sim": iso(o.outage_start_planned_sim),
        "outage_end_planned_sim": iso(o.outage_end_planned_sim),
        "outage_start_actual_sim": iso(o.outage_start_actual_sim),
        "outage_end_actual_sim": iso(o.outage_end_actual_sim),
    }


def order_detail(o: ReplaceOrder, db: Session) -> dict:
    base = order_brief(o, db)
    number = db.get(PhoneNumber, o.number_id)
    card = db.get(SimCard, o.assigned_card_id) if o.assigned_card_id else None
    terminal = None
    if o.terminal_id:
        from .models import Terminal
        terminal = db.get(Terminal, o.terminal_id)
    old_cred = db.get(Credential, o.old_credential_id) if o.old_credential_id else None
    new_cred = db.get(Credential, o.new_credential_id) if o.new_credential_id else None
    from .models import IdentityVerification, Settlement, ExchangeCase
    identities = db.query(IdentityVerification).filter_by(order_id=o.id).all()
    commands = (db.query(NetworkCommand).filter_by(order_id=o.id)
                .order_by(NetworkCommand.id).all())
    cmd_nos = [c.command_no for c in commands]
    receipts = []
    if cmd_nos:
        receipts = (db.query(CommandReceipt)
                    .filter(CommandReceipt.command_no.in_(cmd_nos)
                            | CommandReceipt.original_command_no.in_(cmd_nos))
                    .order_by(CommandReceipt.id).all())
    tasks = db.query(TaskItem).filter_by(order_id=o.id).order_by(TaskItem.id).all()
    settlement = db.query(Settlement).filter_by(order_id=o.id).first()
    exchange = db.query(ExchangeCase).filter_by(order_id=o.id).order_by(ExchangeCase.id.desc()).first()

    base.update({
        "old_credential_id": o.old_credential_id,
        "new_credential_id": o.new_credential_id,
        "terminal_id": o.terminal_id,
        "clerk_id": o.clerk_id,
        "network_operator_id": o.network_operator_id,
        "customer_brief": _customer_brief(db, o.customer_id),
        "remark": o.remark, "fault_flags": o.fault_flags or {},
        "planned": o.planned or {}, "failure_contact": o.failure_contact,
        "activation_checks": o.activation_checks or {},
        "confirmed_at_sim": iso(o.confirmed_at_sim),
        "number": number_dict(number, db) if number else None,
        "card": card_dict(card) if card else None,
        "terminal": {"id": terminal.id, "model": terminal.model, "brand": terminal.brand,
                     "required_form_factor": terminal.required_form_factor,
                     "requires_5g": terminal.requires_5g,
                     "required_profile_type": terminal.required_profile_type} if terminal else None,
        "old_credential": credential_dict(old_cred),
        "new_credential": credential_dict(new_cred),
        "identities": [{"id": i.id, "channel": i.channel, "result": i.result,
                        "score": i.score, "raw": i.raw or {},
                        "verified_at_sim": iso(i.verified_at_sim)} for i in identities],
        "commands": [command_dict(c) for c in commands],
        "receipts": [receipt_dict(r) for r in receipts],
        "tasks": [task_dict(t) for t in tasks],
        "settlement": {"id": settlement.id, "amount": settlement.amount,
                       "currency": settlement.currency, "items": settlement.items or [],
                       "status": settlement.status,
                       "created_at_sim": iso(settlement.created_at_sim),
                       "paid_at_sim": iso(settlement.paid_at_sim)} if settlement else None,
        "exchange": {"id": exchange.id, "case_no": exchange.case_no, "reason": exchange.reason,
                     "status": exchange.status,
                     "old_credential_restorable": exchange.old_credential_restorable,
                     "note": exchange.note, "created_at_sim": iso(exchange.created_at_sim),
                     "completed_at_sim": iso(exchange.completed_at_sim)} if exchange else None,
    })
    return base
