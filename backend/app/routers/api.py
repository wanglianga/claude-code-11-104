"""全部 HTTP API（演示系统保持单一路由模块，便于查阅）。"""
from __future__ import annotations

from collections import Counter

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import settings
from ..db import get_db
from ..models import (
    CommandReceipt,
    Credential,
    NetworkCommand,
    PhoneNumber,
    ReplaceOrder,
    SimCard,
    TaskItem,
    Terminal,
    Plan,
    User,
)
from ..schemas import (
    AssignCardIn,
    AutoIn,
    ExchangeIn,
    FaultIn,
    IdentityIn,
    LateReceiptIn,
    LoginIn,
    OrderCreateIn,
    PlanChangeIn,
    SettleIn,
    TickIn,
)
from ..seed import reset_and_seed
from ..serializers import (
    card_dict,
    command_dict,
    credential_dict,
    number_dict,
    order_brief,
    order_detail,
    plan_dict,
    task_dict,
    user_brief,
)
from ..services import scenarios, workflow
from ..services.auth import current_user, make_token, require_roles
from ..services.clock import get_clock
from ..services.errors import ApiError, NotFoundError
from ..services.simulator import tick as sim_tick

router = APIRouter(prefix="/api")


def _order(db: Session, order_id: int) -> ReplaceOrder:
    o = db.get(ReplaceOrder, order_id)
    if o is None:
        raise NotFoundError("ORDER_NOT_FOUND", f"换卡单 {order_id} 不存在")
    return o


# ---------------------------------------------------------------- 认证/元数据

@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.execute(select(User).where(User.username == body.username)).scalar_one_or_none()
    if u is None or u.password != body.password:
        raise ApiError(401, "BAD_CREDENTIALS", "账号或密码错误（请使用 README 中的测试账号）")
    return {"token": make_token(u.id, u.role), "user": user_brief(u)}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_brief(user)


@router.get("/meta")
def meta(db: Session = Depends(get_db)):
    plans = db.execute(select(Plan).order_by(Plan.id)).scalars().all()
    terminals = db.execute(select(Terminal).order_by(Terminal.id)).scalars().all()
    clock = get_clock(db)
    return {
        "app_name": settings.app_name,
        "plans": [plan_dict(p) for p in plans],
        "terminals": [{"id": t.id, "model": t.model, "brand": t.brand,
                       "required_form_factor": t.required_form_factor,
                       "requires_5g": t.requires_5g,
                       "required_profile_type": t.required_profile_type} for t in terminals],
        "support": {"clerk": settings.support_clerk, "network": settings.support_network,
                    "hotline": settings.support_hotline},
        "sim": {"now_sim": clock.now_sim.isoformat(sep=" "), "auto": clock.auto},
        "durations_min": {"prepare": 2, "stop": 1, "enable": 1, "query": 1, "refresh": 1},
    }


# ---------------------------------------------------------------- 客户/订单

@router.get("/customer/numbers")
def my_numbers(msisdn: str | None = None, db: Session = Depends(get_db),
               user: User = Depends(current_user)):
    stmt = select(PhoneNumber)
    if user.role == "customer":
        stmt = stmt.where(PhoneNumber.customer_id == user.customer_id)
    elif msisdn:
        stmt = stmt.where(PhoneNumber.msisdn == msisdn)
    nums = db.execute(stmt.order_by(PhoneNumber.id)).scalars().all()
    result = []
    for n in nums:
        d = number_dict(n)
        active = db.execute(
            select(Credential).where(Credential.number_id == n.id,
                                     Credential.status == "active")
        ).scalar_one_or_none()
        d["active_credential"] = credential_dict(active)
        result.append(d)
    return {"items": result}


@router.post("/orders")
def create_order(body: OrderCreateIn, db: Session = Depends(get_db),
                 user: User = Depends(require_roles("customer", "clerk", "admin"))):
    o = workflow.create_order(db, user, body)
    db.commit()
    return order_detail(db.get(ReplaceOrder, o.id), db)


@router.get("/orders")
def list_orders(status: str | None = None, msisdn: str | None = None,
                db: Session = Depends(get_db), user: User = Depends(current_user)):
    stmt = select(ReplaceOrder)
    if user.role == "customer":
        stmt = stmt.where(ReplaceOrder.customer_id == user.customer_id)
    if status:
        statuses = [s.strip() for s in status.split(",") if s.strip()]
        if len(statuses) == 1:
            stmt = stmt.where(ReplaceOrder.status == statuses[0])
        elif statuses:
            stmt = stmt.where(ReplaceOrder.status.in_(statuses))
    if msisdn:
        n = db.execute(select(PhoneNumber).where(PhoneNumber.msisdn == msisdn)).scalar_one_or_none()
        if n:
            stmt = stmt.where(ReplaceOrder.number_id == n.id)
    orders = db.execute(stmt.order_by(ReplaceOrder.id.desc())).scalars().all()
    return {"items": [order_brief(o, db) for o in orders]}


@router.get("/orders/{order_id}")
def get_order(order_id: int, db: Session = Depends(get_db),
              user: User = Depends(current_user)):
    return order_detail(_order(db, order_id), db)


@router.post("/orders/{order_id}/verify-identity")
def verify_identity(order_id: int, body: IdentityIn, db: Session = Depends(get_db),
                    user: User = Depends(require_roles("customer", "clerk", "admin"))):
    o = _order(db, order_id)
    workflow.verify_identity(db, o, body.id_number, body.channel)
    db.commit()
    return order_detail(db.get(ReplaceOrder, order_id), db)


@router.post("/orders/{order_id}/cancel")
def cancel_order(order_id: int, db: Session = Depends(get_db),
                 user: User = Depends(require_roles("customer", "clerk", "admin"))):
    o = _order(db, order_id)
    workflow.direct_rollback(db, o)
    db.commit()
    return order_detail(db.get(ReplaceOrder, order_id), db)


@router.post("/orders/{order_id}/settle")
def settle(order_id: int, body: SettleIn, db: Session = Depends(get_db),
           user: User = Depends(require_roles("customer", "clerk", "admin"))):
    o = _order(db, order_id)
    st = workflow.settle_order(db, o, body.channel)
    db.commit()
    return {"settlement": {"id": st.id, "amount": st.amount, "status": st.status,
                           "paid_at_sim": st.paid_at_sim.isoformat(sep=" ")}}


# ---------------------------------------------------------------- 营业台

@router.get("/clerk/workbench")
def clerk_workbench(db: Session = Depends(get_db),
                    user: User = Depends(require_roles("clerk", "admin"))):
    queue = db.execute(
        select(ReplaceOrder).order_by(ReplaceOrder.id.desc())
    ).scalars().all()
    cards = db.execute(select(SimCard).order_by(SimCard.card_no)).scalars().all()
    tasks = db.execute(
        select(TaskItem).where(TaskItem.assignee_role == "clerk")
        .order_by(TaskItem.status.desc(), TaskItem.id.desc())
    ).scalars().all()
    return {
        "orders": [order_brief(o, db) for o in queue],
        "cards": [card_dict(c) for c in cards],
        "tasks": [task_dict(t) for t in tasks],
        "stock_counts": dict(Counter(c.status for c in cards)),
    }


@router.get("/cards")
def list_cards(status: str | None = None, db: Session = Depends(get_db),
               user: User = Depends(current_user)):
    stmt = select(SimCard)
    if status:
        stmt = stmt.where(SimCard.status == status)
    cards = db.execute(stmt.order_by(SimCard.card_no)).scalars().all()
    return {"items": [card_dict(c) for c in cards],
            "counts": dict(Counter(c.status for c in
                                   db.execute(select(SimCard)).scalars().all()))}


@router.post("/orders/{order_id}/assign-card")
def assign_card(order_id: int, body: AssignCardIn, db: Session = Depends(get_db),
                user: User = Depends(require_roles("clerk", "admin"))):
    o = _order(db, order_id)
    # 停旧未知时禁止借改分卡“另开第二张卡”
    workflow.reassign_card_guard(db, o)
    workflow.assign_card(db, o, card_id=body.card_id, card_no=body.card_no, auto=body.auto)
    o.clerk_id = user.id
    db.commit()
    return order_detail(db.get(ReplaceOrder, order_id), db)


# ---------------------------------------------------------------- 网络台

@router.get("/network/workbench")
def network_workbench(db: Session = Depends(get_db),
                      user: User = Depends(require_roles("network", "admin"))):
    cmds = db.execute(select(NetworkCommand).order_by(NetworkCommand.id.desc()).limit(100)).scalars().all()
    tasks = db.execute(
        select(TaskItem).where(TaskItem.assignee_role == "network")
        .order_by(TaskItem.status.desc(), TaskItem.id.desc())
    ).scalars().all()
    orders = db.execute(select(ReplaceOrder).order_by(ReplaceOrder.id.desc())).scalars().all()
    receipts = db.execute(select(CommandReceipt).order_by(CommandReceipt.id.desc()).limit(50)).scalars().all()
    from ..serializers import receipt_dict
    return {"commands": [command_dict(c) for c in cmds],
            "tasks": [task_dict(t) for t in tasks],
            "orders": [order_brief(o, db) for o in orders],
            "recent_receipts": [receipt_dict(r) for r in receipts]}


@router.get("/commands")
def list_commands(status: str | None = None, order_id: int | None = None,
                  db: Session = Depends(get_db), user: User = Depends(current_user)):
    stmt = select(NetworkCommand)
    if status:
        stmt = stmt.where(NetworkCommand.status == status)
    if order_id:
        stmt = stmt.where(NetworkCommand.order_id == order_id)
    cmds = db.execute(stmt.order_by(NetworkCommand.id.desc())).scalars().all()
    return {"items": [command_dict(c) for c in cmds]}


@router.post("/commands/{command_id}/query")
def query_command(command_id: int, db: Session = Depends(get_db),
                  user: User = Depends(require_roles("network", "admin"))):
    cmd = workflow.query_command(db, command_id, user)
    db.commit()
    return command_dict(db.get(NetworkCommand, cmd.id))


def _network_action(order_id: int, action: str, db: Session, user: User):
    o = _order(db, order_id)
    fn = {
        "report-loss": workflow.action_report_loss,
        "prepare": workflow.action_prepare,
        "stop": workflow.action_stop,
        "enable": workflow.action_enable,
        "refresh": workflow.action_refresh,
    }[action]
    cmd = fn(db, o, user)
    o.network_operator_id = user.id
    db.commit()
    return command_dict(db.get(NetworkCommand, cmd.id)) if cmd else {"ok": True}


@router.post("/orders/{order_id}/report-loss")
def act_loss(order_id: int, db: Session = Depends(get_db),
             user: User = Depends(require_roles("network", "admin"))):
    return _network_action(order_id, "report-loss", db, user)


@router.post("/orders/{order_id}/prepare")
def act_prepare(order_id: int, db: Session = Depends(get_db),
                user: User = Depends(require_roles("network", "admin"))):
    return _network_action(order_id, "prepare", db, user)


@router.post("/orders/{order_id}/stop")
def act_stop(order_id: int, db: Session = Depends(get_db),
             user: User = Depends(require_roles("network", "admin"))):
    return _network_action(order_id, "stop", db, user)


@router.post("/orders/{order_id}/enable")
def act_enable(order_id: int, db: Session = Depends(get_db),
               user: User = Depends(require_roles("network", "admin"))):
    return _network_action(order_id, "enable", db, user)


@router.post("/orders/{order_id}/refresh")
def act_refresh(order_id: int, db: Session = Depends(get_db),
                user: User = Depends(require_roles("network", "admin"))):
    return _network_action(order_id, "refresh", db, user)


# ---------------------------------------------------------------- 激活核验

@router.get("/activation/workbench")
def activation_workbench(db: Session = Depends(get_db),
                         user: User = Depends(current_user)):
    creds = db.execute(select(Credential).order_by(Credential.id.desc())).scalars().all()
    orders = db.execute(
        select(ReplaceOrder).where(
            ReplaceOrder.status.in_(["active_pending_confirm", "confirmed", "settled",
                                     "enabling_new", "enable_rejected", "old_stopped"])
        ).order_by(ReplaceOrder.id.desc())
    ).scalars().all()
    return {"credentials": [credential_dict(c) for c in creds],
            "orders": [order_detail(o, db) for o in orders]}


@router.post("/orders/{order_id}/probes")
def probes(order_id: int, db: Session = Depends(get_db),
           user: User = Depends(require_roles("customer", "network", "admin"))):
    o = _order(db, order_id)
    checks = workflow.run_probes(db, o, user)
    db.commit()
    return checks


@router.post("/orders/{order_id}/confirm")
def confirm(order_id: int, db: Session = Depends(get_db),
            user: User = Depends(require_roles("customer", "admin"))):
    o = _order(db, order_id)
    workflow.confirm_activation(db, o, user)
    db.commit()
    return order_detail(db.get(ReplaceOrder, order_id), db)


# ---------------------------------------------------------------- 受控退换

@router.post("/orders/{order_id}/exchange")
def exchange(order_id: int, body: ExchangeIn, db: Session = Depends(get_db),
             user: User = Depends(require_roles("customer", "clerk", "admin"))):
    o = _order(db, order_id)
    case = workflow.request_exchange(db, o, body.reason, user)
    db.commit()
    return {"case_id": case.id, "case_no": case.case_no, "status": case.status}


@router.post("/exchange/{case_id}/complete")
def complete_exchange(case_id: int, db: Session = Depends(get_db),
                      user: User = Depends(require_roles("network", "admin"))):
    case = workflow.complete_exchange(db, case_id, user)
    db.commit()
    return {"case_id": case.id, "case_no": case.case_no, "status": case.status}


# ---------------------------------------------------------------- 任务

@router.get("/tasks")
def tasks(assignee: str | None = None, status_filter: str | None = Query(default=None, alias="status"),
          db: Session = Depends(get_db), user: User = Depends(current_user)):
    stmt = select(TaskItem)
    if assignee:
        stmt = stmt.where(TaskItem.assignee_role == assignee)
    if status_filter:
        stmt = stmt.where(TaskItem.status == status_filter)
    rows = db.execute(stmt.order_by(TaskItem.status.desc(), TaskItem.id.desc())).scalars().all()
    return {"items": [task_dict(t) for t in rows]}


# ---------------------------------------------------------------- 模拟时钟

@router.get("/sim")
def sim_state(db: Session = Depends(get_db)):
    c = get_clock(db)
    return {"now_sim": c.now_sim.isoformat(sep=" "), "auto": c.auto,
            "tick_real_ms": settings.sim_tick_real_ms}


@router.post("/sim/tick")
def sim_tick_api(body: TickIn, db: Session = Depends(get_db),
                 user: User = Depends(current_user)):
    result = sim_tick(db, max(1, min(body.minutes, 60)))
    db.commit()
    return result


@router.post("/sim/auto")
def sim_auto(body: AutoIn, db: Session = Depends(get_db),
             user: User = Depends(current_user)):
    c = get_clock(db, lock=True)
    c.auto = body.enabled
    db.commit()
    return {"auto": c.auto}


# ---------------------------------------------------------------- 场景编排

@router.post("/scenarios/plan-change")
def scenario_plan_change(body: PlanChangeIn, db: Session = Depends(get_db),
                         user: User = Depends(require_roles("clerk", "network", "admin"))):
    result = scenarios.approve_plan_change(db, body.msisdn, body.to_plan_code, body.approve)
    db.commit()
    return result


@router.post("/scenarios/late-receipt")
def scenario_late(body: LateReceiptIn, db: Session = Depends(get_db),
                  user: User = Depends(require_roles("network", "admin"))):
    result = scenarios.schedule_late_old_enable(db, body.msisdn, body.delay_min, body.duplicate)
    db.commit()
    return result


@router.post("/orders/{order_id}/faults")
def set_faults(order_id: int, body: FaultIn, db: Session = Depends(get_db),
               user: User = Depends(require_roles("clerk", "network", "admin"))):
    o = _order(db, order_id)
    o.fault_flags = body.fault_flags
    db.commit()
    return {"id": o.id, "fault_flags": o.fault_flags}


# ---------------------------------------------------------------- 测试/核对

@router.post("/test/reset")
def test_reset():
    if not settings.allow_reset:
        raise ApiError(403, "RESET_DISABLED", "服务器未启用 ALLOW_RESET")
    reset_and_seed()
    return {"ok": True, "message": "已重建虚构数据"}


@router.get("/test/snapshot")
def test_snapshot(db: Session = Depends(get_db)):
    """验证脚本用的全量不变量快照。"""
    numbers = db.execute(select(PhoneNumber).order_by(PhoneNumber.id)).scalars().all()
    per_number = []
    for n in numbers:
        creds = db.execute(select(Credential).where(Credential.number_id == n.id)).scalars().all()
        per_number.append({
            "msisdn": n.msisdn, "plan_version": n.plan_version,
            "billing_cycle_day": n.billing_cycle_day,
            "cycle_data_used_mb": n.cycle_data_used_mb,
            "cycle_voice_used_min": n.cycle_voice_used_min,
            "benefits_used_count": n.benefits_used_count,
            "active_credential_ids": [c.id for c in creds if c.status == "active"],
            "credentials": [{"id": c.id, "status": c.status,
                             "card_id": c.card_id,
                             "profile_plan_version": c.profile_plan_version,
                             "profile_stale": c.profile_stale} for c in creds],
        })
    cards = db.execute(select(SimCard)).scalars().all()
    orders = db.execute(select(ReplaceOrder)).scalars().all()
    tasks = db.execute(select(TaskItem)).scalars().all()
    receipts = db.execute(select(CommandReceipt)).scalars().all()
    return {
        "numbers": per_number,
        "card_counts": dict(Counter(c.status for c in cards)),
        "cards": [card_dict(c) for c in cards],
        "order_counts": dict(Counter(o.status for o in orders)),
        "orders": [{"id": o.id, "order_no": o.order_no, "msisdn": None,
                    "status": o.status, "strategy": o.strategy,
                    "assigned_card_id": o.assigned_card_id,
                    "outage_start_actual_sim": o.outage_start_actual_sim.isoformat(sep=" ") if o.outage_start_actual_sim else None,
                    "outage_end_actual_sim": o.outage_end_actual_sim.isoformat(sep=" ") if o.outage_end_actual_sim else None}
                   for o in orders],
        "open_tasks": [task_dict(t) for t in tasks if t.status == "open"],
        "receipts": [{"command_no": r.command_no, "applied": r.applied,
                      "ignore_reason": r.ignore_reason} for r in receipts],
        "active_credential_total": db.scalar(
            select(func.count()).select_from(Credential).where(Credential.status == "active")
        ),
    }
