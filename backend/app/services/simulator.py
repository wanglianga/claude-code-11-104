"""虚构网络/制卡适配器 + 模拟时钟推进引擎。

- 指令到期时适配器先形成“网络侧真实结果”(adapter_outcome)；
- lose_response 故障下真实结果已发生，但平台收不到回执 -> 超时转 unknown；
- scheduled_receipts 用来模拟“旧启用回执晚到”等乱序/重复回执。
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..enums import CommandStatus
from ..models import (
    CommandReceipt,
    Credential,
    NetworkCommand,
    PhoneNumber,
    ScheduledReceipt,
    SimCard,
    Terminal,
)
from .clock import advance, gen_no, get_clock, now_sim
from .effects import apply_outcome
from .tasks import open_task


def adapter_execute(db: Session, cmd: NetworkCommand) -> dict:
    """虚构适配器的真实执行逻辑（不改动平台订单状态）。"""
    order = None
    terminal = None
    card = None
    if cmd.order_id:
        from ..models import ReplaceOrder
        order = db.get(ReplaceOrder, cmd.order_id)
        if order and order.terminal_id:
            terminal = db.get(Terminal, order.terminal_id)
    cred = db.get(Credential, cmd.credential_id) if cmd.credential_id else None
    if cred and cred.card_id:
        card = db.get(SimCard, cred.card_id)
    elif order and order.assigned_card_id:
        card = db.get(SimCard, order.assigned_card_id)

    # 显式故障注入优先
    if cmd.fault_mode == "reject_incompatible":
        return {"outcome": "rejected", "code": "PROFILE_INCOMPATIBLE",
                "message": "适配器注入：新配置与终端/卡 profile 不兼容（虚构）"}

    if cmd.kind == "prepare_profile":
        if terminal and card:
            if card.profile_type != terminal.required_profile_type:
                return {
                    "outcome": "rejected", "code": "PROFILE_INCOMPATIBLE",
                    "message": f"终端 {terminal.model} 要求 {terminal.required_profile_type}，"
                               f"卡 {card.card_no} 为 {card.profile_type}",
                }
            if terminal.requires_5g and card.network_gen != "5G":
                return {
                    "outcome": "rejected", "code": "CARD_NETWORK_GEN_MISMATCH",
                    "message": f"终端 {terminal.model} 要求 5G，卡 {card.card_no} 为 {card.network_gen}",
                }
        return {"outcome": "succeeded", "code": "0", "message": "配置制作完成（未激活）"}

    if cmd.kind == "enable_credential":
        # 启用前校验配置是否仍继承最新已确认套餐
        if cred:
            number = db.get(PhoneNumber, cmd.number_id)
            if number and (cred.profile_stale
                           or cred.profile_plan_version < number.plan_version):
                return {
                    "outcome": "rejected", "code": "PROFILE_PLAN_STALE",
                    "message": f"配置套餐版本 v{cred.profile_plan_version} 落后于已确认 "
                               f"v{number.plan_version}，需刷新配置",
                }
        return {"outcome": "succeeded", "code": "0", "message": "新凭据启用成功"}

    if cmd.kind == "stop_credential":
        return {"outcome": "succeeded", "code": "0", "message": "旧凭据已停用"}

    if cmd.kind == "refresh_profile":
        return {"outcome": "succeeded", "code": "0", "message": "配置已刷新到最新已确认套餐/权限"}

    if cmd.kind == "query_command":
        target = db.get(NetworkCommand, cmd.relates_to_id) if cmd.relates_to_id else None
        truth = target.adapter_outcome if target else None
        return {"outcome": "succeeded", "code": "0",
                "message": "原指令查询完成", "original_outcome": truth}

    if cmd.kind == "report_loss":
        return {"outcome": "succeeded", "code": "0", "message": "挂失已受理并加入风险名单"}

    return {"outcome": "succeeded", "code": "0", "message": "ok"}


def _deliver_receipt(db: Session, cmd: NetworkCommand, outcome: dict) -> CommandReceipt:
    rcp = CommandReceipt(
        receipt_no=gen_no(db, "RCP"),
        command_no=cmd.command_no,
        outcome=outcome.get("outcome", "succeeded"),
        code=outcome.get("code"),
        message=outcome.get("message"),
        raw=outcome,
        received_at_sim=now_sim(db),
        applied=True,
    )
    db.add(rcp)
    db.flush()
    apply_outcome(db, cmd, outcome)
    return rcp


def _deliver_scheduled(db: Session, sr: ScheduledReceipt, events: list) -> None:
    sr.delivered = True
    sr.delivered_at_sim = now_sim(db)
    cmd = db.execute(
        select(NetworkCommand).where(NetworkCommand.command_no == sr.command_no)
    ).scalar_one_or_none()

    terminal = cmd is not None and cmd.status in (
        CommandStatus.SUCCEEDED, CommandStatus.REJECTED
    )
    if sr.duplicate or terminal or cmd is None:
        reason = ("duplicate_late_receipt_ignored" if sr.duplicate
                  else "command_already_terminal_ignored" if terminal
                  else "unknown_command_no_ignored")
        rcp = CommandReceipt(
            receipt_no=gen_no(db, "RCP"),
            command_no=sr.command_no,
            original_command_no=sr.original_command_no,
            outcome=sr.outcome, code=sr.code, message=sr.message,
            raw=sr.payload or {}, received_at_sim=now_sim(db),
            applied=False, ignore_reason=reason,
        )
        db.add(rcp)
        db.flush()
        events.append({"type": "late_receipt_ignored", "command_no": sr.command_no,
                       "reason": reason, "receipt_no": rcp.receipt_no})
        return

    # 指令仍在途/未知：迟到回执是有效结果
    outcome = {"outcome": sr.outcome, "code": sr.code, "message": sr.message}
    rcp = _deliver_receipt(db, cmd, outcome)
    events.append({"type": "late_receipt_applied", "command_no": sr.command_no,
                   "receipt_no": rcp.receipt_no})


def tick(db: Session, minutes: int = 1) -> dict:
    """推进模拟时钟 N 分钟，逐分钟处理，保证时刻断言稳定。"""
    events: list[dict] = []
    for _ in range(max(1, minutes)):
        clock = advance(db, 1)
        t = clock.now_sim

        # 1) 计划回执（含迟到/重复回执）
        scheduled = db.execute(
            select(ScheduledReceipt).where(
                ScheduledReceipt.delivered.is_(False),
                ScheduledReceipt.deliver_at_sim <= t,
            ).with_for_update(skip_locked=True)
        ).scalars().all()
        for sr in scheduled:
            _deliver_scheduled(db, sr, events)

        # 2) 到期指令：适配器形成真实结果并尝试投递回执
        due = db.execute(
            select(NetworkCommand).where(
                NetworkCommand.status == CommandStatus.SENT,
                NetworkCommand.due_at_sim <= t,
            ).with_for_update(skip_locked=True)
        ).scalars().all()
        for cmd in due:
            if cmd.adapter_outcome is None:
                truth = adapter_execute(db, cmd)
                cmd.adapter_outcome = truth
                cmd.adapter_executed_at_sim = t
            truth = cmd.adapter_outcome
            if cmd.fault_mode == "lose_response":
                # 网络侧已执行，但回执在传输中丢失：平台保持 sent，等待 unknown 判定
                events.append({"type": "response_lost", "command_no": cmd.command_no,
                               "kind": cmd.kind})
                continue
            rcp = _deliver_receipt(db, cmd, truth)
            events.append({"type": "receipt", "command_no": cmd.command_no,
                           "status": cmd.status, "receipt_no": rcp.receipt_no})

        # 3) 超过未知宽限期仍停留在 sent -> 结果未知，禁止当失败处理
        stale = db.execute(
            select(NetworkCommand).where(
                NetworkCommand.status == CommandStatus.SENT,
                NetworkCommand.unknown_at_sim <= t,
            ).with_for_update(skip_locked=True)
        ).scalars().all()
        for cmd in stale:
            cmd.status = CommandStatus.UNKNOWN
            cmd.response_code = "RESULT_UNKNOWN"
            cmd.response_message = "超时未获回执，结果未知；必须先查询原指令，不能按失败另开新卡/新凭据"
            if cmd.kind == "stop_credential" and cmd.order_id:
                from ..models import ReplaceOrder
                order = db.get(ReplaceOrder, cmd.order_id)
                if order and order.status not in ("old_stopped", "active_pending_confirm",
                                                  "confirmed", "settled"):
                    order.status = "stop_old_unknown"
                    open_task(
                        db, assignee="network", type_="query_stop",
                        title="停旧指令结果未知：先查询原指令",
                        detail=f"指令 {cmd.command_no} 超时无回执。只能查询原指令核对网络真实结果，"
                               f"不得按超时当失败去开第二张卡或直接启用新卡。",
                        order_id=order.id, action_hint="query",
                    )
            else:
                open_task(db, assignee="network", type_="query_command",
                          title=f"{cmd.kind} 指令结果未知，需查询原指令",
                          detail=f"指令 {cmd.command_no} 必须先查询核对。",
                          order_id=cmd.order_id)
            events.append({"type": "unknown", "command_no": cmd.command_no, "kind": cmd.kind})

    db.flush()
    return {"now_sim": get_clock(db).now_sim.isoformat(sep=" "), "events": events}
