"""回执落地的副作用：推进订单状态机、凭据状态、卡库存与待办。

所有函数只在拿到“确认回执”后调用；结果未知时绝不允许在这里猜成功/失败。
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..enums import (
    CardStatus,
    CommandKind,
    CommandStatus,
    CredentialStatus,
    OrderStatus,
    TaskAssignee,
)
from ..models import Credential, NetworkCommand, PhoneNumber, ReplaceOrder, SimCard
from .clock import gen_no, now_sim
from .tasks import complete_tasks, open_task


def build_profile_snapshot(number: PhoneNumber) -> dict:
    """新配置继承当前已确认套餐与业务权限；账期日也原样带入配置。"""
    plan = number.plan
    return {
        "msisdn": number.msisdn,
        "plan_code": plan.code if plan else None,
        "plan_name": plan.name if plan else None,
        "plan_version": number.plan_version,
        "data_mb": plan.data_mb if plan else None,
        "voice_min": plan.voice_min if plan else None,
        "permissions": list(plan.permissions or []) if plan else [],
        "billing_cycle_day": number.billing_cycle_day,
        "inherited_confirmed_plan": True,
    }


def _lock_number(db: Session, number_id: int) -> PhoneNumber:
    return db.execute(
        select(PhoneNumber).where(PhoneNumber.id == number_id).with_for_update()
    ).scalar_one()


def _release_card(db: Session, order: ReplaceOrder) -> None:
    if not order.assigned_card_id:
        return
    card = db.get(SimCard, order.assigned_card_id)
    if card and card.status == CardStatus.RESERVED:
        card.status = CardStatus.IN_STOCK
        card.reserved_order_id = None


def apply_outcome(db: Session, cmd: NetworkCommand, outcome: dict) -> bool:
    """把适配器/查询拿到的确定结果落到领域状态。重复调用安全。"""
    if cmd.status in (CommandStatus.SUCCEEDED, CommandStatus.REJECTED):
        return False

    ok = outcome.get("outcome") == "succeeded"
    ts = cmd.adapter_executed_at_sim or now_sim(db)
    cmd.response_code = outcome.get("code")
    cmd.response_message = outcome.get("message")
    cmd.completed_at_sim = ts
    cmd.status = CommandStatus.SUCCEEDED if ok else CommandStatus.REJECTED

    order = db.get(ReplaceOrder, cmd.order_id) if cmd.order_id else None
    kind = cmd.kind

    if kind == CommandKind.QUERY_COMMAND:
        return _on_query(db, cmd, outcome, order)

    if kind == CommandKind.PREPARE_PROFILE:
        _on_prepare(db, cmd, outcome, ok, ts, order)
    elif kind == CommandKind.STOP_CREDENTIAL:
        _on_stop(db, cmd, outcome, ok, ts, order)
    elif kind == CommandKind.ENABLE_CREDENTIAL:
        _on_enable(db, cmd, outcome, ok, ts, order)
    elif kind == CommandKind.REFRESH_PROFILE:
        _on_refresh(db, cmd, ok, ts, order)
    elif kind == CommandKind.REPORT_LOSS:
        if order and ok:
            order.status = OrderStatus.LOSS_REPORTED
    db.flush()
    return True


def _on_query(db, cmd, outcome, order) -> bool:
    """查询原指令：以原指令的适配器留底为准，再把原结果真正落地。"""
    target_id = cmd.relates_to_id or (outcome.get("relates_to_id") if outcome else None)
    if not target_id:
        if order:
            open_task(db, assignee=TaskAssignee.NETWORK, type_="manual_reconcile",
                      title="查询指令缺少原指令关联，需人工核对",
                      detail=f"查询指令 {cmd.command_no} 未关联原指令。",
                      order_id=order.id)
        return True
    target = db.get(NetworkCommand, target_id)
    if target is None:
        return True

    truth = target.adapter_outcome or outcome.get("original_outcome") or {
        "outcome": "succeeded", "code": "0", "message": "查询原指令确认成功"
    }
    # 为“原指令”补一张查询回执留痕
    from ..models import CommandReceipt
    rcp = CommandReceipt(
        receipt_no=gen_no(db, "RCP"),
        command_no=target.command_no,
        original_command_no=cmd.command_no,
        outcome=truth.get("outcome", "succeeded"),
        code=truth.get("code"),
        message=f"[查询原指令 {cmd.command_no}] {truth.get('message', '')}",
        raw={"via_query": cmd.command_no, "truth": truth},
        received_at_sim=now_sim(db),
        applied=True,
    )
    db.add(rcp)
    db.flush()

    if target.status not in (CommandStatus.SUCCEEDED, CommandStatus.REJECTED):
        apply_outcome(db, target, truth)

    if order:
        complete_tasks(db, order_id=order.id, types=["query_stop", "query_command"])
        # 下一步待办已由 apply_outcome(target) 的状态副作用创建，这里不再重复开单
    return True


def _on_prepare(db, cmd, outcome, ok, ts, order):
    cred = db.get(Credential, cmd.credential_id) if cmd.credential_id else None
    if not order:
        return
    complete_tasks(db, order_id=order.id, types=["prepare_profile"])
    if ok and cred:
        cred.status = CredentialStatus.PREPARED
        cred.prepared_at_sim = ts
        if order.strategy == "stop_first":
            # 旧凭据已停用，新配置也就绪：统一落在 old_stopped（可直接启用）
            order.status = OrderStatus.OLD_STOPPED
            open_task(db, assignee=TaskAssignee.NETWORK, type_="enable_new",
                      title="新配置已就绪，下发启用指令",
                      detail="先停旧路径：旧凭据已停用，启用后恢复通信。",
                      order_id=order.id, action_hint="enable")
        else:
            order.status = OrderStatus.PREPARED
            open_task(db, assignee=TaskAssignee.NETWORK, type_="stop_old",
                      title="未激活新配置已就绪，下发停旧指令",
                      detail="先准备路径：旧卡仍可用，停旧确认后第 3~4 分钟为预计中断窗口。",
                      order_id=order.id, action_hint="stop")
    else:
        if cred:
            cred.status = CredentialStatus.PREPARE_REJECTED
        order.status = OrderStatus.PREPARE_FAILED
        _release_card(db, order)
        reason = outcome.get("code", "PREPARE_REJECTED")
        open_task(
            db, assignee=TaskAssignee.CLERK, type_="reassign_card",
            title="新配置被网络拒绝，需重新分配兼容卡",
            detail=f"准备配置拒绝码 {reason}：{outcome.get('message', '')}。"
                   f"原卡已释放回虚构卡库；请改分兼容卡后重新准备，不要在未处理本指令前另开新卡。",
            order_id=order.id, action_hint="assign",
        )


def _on_stop(db, cmd, outcome, ok, ts, order):
    cred = db.get(Credential, cmd.credential_id) if cmd.credential_id else None
    if not order:
        return
    complete_tasks(db, order_id=order.id, types=["stop_old"])
    if ok:
        if cred:
            cred.status = (CredentialStatus.LOSS_BLOCKED
                           if order.reason == "lost" else CredentialStatus.STOPPED)
            cred.stopped_at_sim = ts
            # 旧实体卡随旧凭据一起退役，不再算作在用卡
            old_card = db.get(SimCard, cred.card_id) if cred.card_id else None
            if old_card and old_card.status == CardStatus.IN_USE:
                old_card.status = CardStatus.RETIRED
        # 以网络侧实际执行时刻作为中断起点（回执丢失时尤其重要）
        order.outage_start_actual_sim = cmd.adapter_executed_at_sim or ts
        order.status = OrderStatus.OLD_STOPPED
        if order.strategy == "stop_first":
            open_task(db, assignee=TaskAssignee.NETWORK, type_="prepare_profile",
                      title="旧卡已停用，立即准备新配置（客户无服务中）",
                      detail="先停旧路径：预计中断 T+1~T+4，请优先处理。",
                      order_id=order.id, action_hint="prepare")
        else:
            open_task(db, assignee=TaskAssignee.NETWORK, type_="enable_new",
                      title="旧卡已停用，下发启用新配置",
                      detail="先准备路径：新配置早已就绪，启用确认后结束中断。",
                      order_id=order.id, action_hint="enable")
    else:
        # 明确被拒：回退到可重试状态
        order.status = (OrderStatus.PREPARED if order.strategy == "prepare_first"
                        else OrderStatus.CARD_ASSIGNED)
        open_task(db, assignee=TaskAssignee.NETWORK, type_="retry_stop",
                  title="停旧指令被拒绝，需处理后重试",
                  detail=f"{outcome.get('code')}: {outcome.get('message', '')}",
                  order_id=order.id, action_hint="stop")


def _on_enable(db, cmd, outcome, ok, ts, order):
    cred = db.get(Credential, cmd.credential_id) if cmd.credential_id else None
    if not order or not cred:
        return
    complete_tasks(db, order_id=order.id, types=["enable_new"])
    if not ok:
        code = outcome.get("code", "ENABLE_REJECTED")
        order.status = OrderStatus.ENABLE_REJECTED
        if code == "PROFILE_PLAN_STALE":
            open_task(
                db, assignee=TaskAssignee.NETWORK, type_="refresh_profile",
                title="配置套餐版本已过期，需刷新配置后再启用",
                detail="准备期间有已获批的套餐/权限变更；当前配置快照不是最新已确认版本。"
                       "请先 refresh_profile，再重新启用。账期与已用权益不受影响。",
                order_id=order.id, action_hint="refresh",
            )
        else:
            open_task(db, assignee=TaskAssignee.NETWORK, type_="retry_enable",
                      title="启用新配置被拒绝，需处理后重试",
                      detail=f"{code}: {outcome.get('message', '')}",
                      order_id=order.id, action_hint="enable")
        return

    number = _lock_number(db, order.number_id)
    # 唯一激活约束的应用层守卫；数据库部分唯一索引是最终防线
    cred.status = CredentialStatus.ACTIVE
    cred.activated_at_sim = ts
    try:
        db.flush()
    except IntegrityError as exc:  # 并发下撞 ux_ss_credentials_one_active
        raise RuntimeError("DUPLICATE_ACTIVE_CREDENTIAL") from exc

    card = db.get(SimCard, cred.card_id) if cred.card_id else None
    if card:
        card.status = CardStatus.IN_USE
        card.reserved_order_id = None
    number.service_status = "in_service"

    order.outage_end_actual_sim = ts
    order.status = OrderStatus.ACTIVE_PENDING_CONFIRM
    open_task(
        db, assignee=TaskAssignee.CUSTOMER, type_="confirm_activation",
        title="请确认新卡信号、上网与通话均正常",
        detail="网络侧已启用成功，但只有客户确认新卡实际可用后才进入结清。",
        order_id=order.id, action_hint="confirm",
    )


def _on_refresh(db, cmd, ok, ts, order):
    cred = db.get(Credential, cmd.credential_id) if cmd.credential_id else None
    complete_tasks(db, order_id=order.id, types=["refresh_profile"])
    if ok and cred:
        number = _lock_number(db, order.number_id)
        snap = build_profile_snapshot(number)
        # 保留卡/凭据硬件标识
        old = cred.profile_snapshot or {}
        snap["ki_ref"] = old.get("ki_ref")
        snap["profile_type"] = old.get("profile_type")
        cred.profile_snapshot = snap
        cred.profile_plan_version = number.plan_version
        cred.profile_stale = False
        order.status = OrderStatus.OLD_STOPPED
        open_task(db, assignee=TaskAssignee.NETWORK, type_="enable_new",
                  title="配置已刷新到最新已确认套餐，下发启用",
                  detail="套餐内容与业务权限已更新；账期日和已用权益保持不变。",
                  order_id=order.id, action_hint="enable")
    elif order:
        open_task(db, assignee=TaskAssignee.NETWORK, type_="retry_refresh",
                  title="刷新配置失败，需重试", detail=cmd.response_message or "",
                  order_id=order.id, action_hint="refresh")
