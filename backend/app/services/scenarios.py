"""验证场景编排：套餐变更获批、旧启用回执晚到等。"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Credential,
    NetworkCommand,
    PhoneNumber,
    Plan,
    PlanChangeRequest,
    ScheduledReceipt,
)
from .clock import now_sim
from .errors import NotFoundError


def approve_plan_change(db: Session, msisdn: str, to_plan_code: str,
                        approve: bool = True) -> dict:
    number = db.execute(
        select(PhoneNumber).where(PhoneNumber.msisdn == msisdn).with_for_update()
    ).scalar_one_or_none()
    if number is None:
        raise NotFoundError("NUMBER_NOT_FOUND", f"号码 {msisdn} 不存在")
    to_plan = db.execute(select(Plan).where(Plan.code == to_plan_code)).scalar_one_or_none()
    if to_plan is None:
        raise NotFoundError("PLAN_NOT_FOUND", f"套餐 {to_plan_code} 不存在")

    req = PlanChangeRequest(
        number_id=number.id, from_plan_id=number.plan_id, to_plan_id=to_plan.id,
        status="requested", requested_at_sim=now_sim(db),
    )
    db.add(req)
    db.flush()

    before = {
        "plan_version": number.plan_version,
        "billing_cycle_day": number.billing_cycle_day,
        "cycle_data_used_mb": number.cycle_data_used_mb,
        "cycle_voice_used_min": number.cycle_voice_used_min,
        "benefits_used_count": number.benefits_used_count,
    }
    if approve:
        req.status = "approved"
        req.approved_at_sim = now_sim(db)
        number.plan_id = to_plan.id
        number.plan_version += 1  # 已确认套餐版本推进；账期日与已用权益字段不动

        # 若新配置已制作但未启用，标记快照过期，启用守卫会要求 refresh
        creds = db.execute(
            select(Credential).where(
                Credential.number_id == number.id,
                Credential.status.in_(["prepared", "preparing"]),
            )
        ).scalars().all()
        for c in creds:
            if c.profile_plan_version < number.plan_version:
                c.profile_stale = True
        db.flush()

    return {
        "change_request_id": req.id, "status": req.status,
        "before": before,
        "after": {
            "plan_version": number.plan_version,
            "plan_code": to_plan.code,
            "billing_cycle_day": number.billing_cycle_day,
            "cycle_data_used_mb": number.cycle_data_used_mb,
            "cycle_voice_used_min": number.cycle_voice_used_min,
            "benefits_used_count": number.benefits_used_count,
        },
    }


def schedule_late_old_enable(db: Session, msisdn: str, delay_min: int = 2,
                             duplicate: bool = True) -> dict:
    number = db.execute(
        select(PhoneNumber).where(PhoneNumber.msisdn == msisdn)
    ).scalar_one_or_none()
    if number is None:
        raise NotFoundError("NUMBER_NOT_FOUND", f"号码 {msisdn} 不存在")

    # 找该号码历史原始启用指令（种子数据里的 CMD-SEED-EN-xx）
    cmd = db.execute(
        select(NetworkCommand)
        .join(Credential, Credential.original_enable_command_id == NetworkCommand.id)
        .where(Credential.number_id == number.id)
        .order_by(NetworkCommand.id)
    ).scalars().first()
    if cmd is None:
        # 兜底：直接找最早的 enable 指令
        cmd = db.execute(
            select(NetworkCommand).where(
                NetworkCommand.number_id == number.id,
                NetworkCommand.kind == "enable_credential",
            ).order_by(NetworkCommand.id)
        ).scalars().first()
    if cmd is None:
        raise NotFoundError("ENABLE_COMMAND_NOT_FOUND", "找不到可重放的旧启用指令")

    sr = ScheduledReceipt(
        deliver_at_sim=now_sim(db) + timedelta(minutes=delay_min),
        command_no=cmd.command_no,
        original_command_no=cmd.command_no,
        outcome="succeeded", code="0",
        message="旧启用指令的迟到/重复成功回执（虚构网络延迟重投）",
        payload={"late": True, "duplicate": duplicate},
        duplicate=duplicate,
    )
    db.add(sr)
    db.flush()
    return {"scheduled_receipt_id": sr.id, "command_no": cmd.command_no,
            "deliver_at_sim": sr.deliver_at_sim.isoformat(sep=" "),
            "delay_min": delay_min, "duplicate": duplicate}
