"""换卡办理工作流：创建（并发唯一在办）、核验、分卡、动作守卫、确认结清与退换。"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import settings
from ..enums import (
    OPEN_ORDER_STATUSES,
    CardStatus,
    CommandKind,
    CommandStatus,
    CredentialStatus,
    OrderStatus,
    Reason,
    Strategy,
    TaskAssignee,
)
from ..models import (
    Credential,
    Customer,
    IdentityVerification,
    NetworkCommand,
    PhoneNumber,
    Plan,
    ReplaceOrder,
    Settlement,
    SimCard,
    Terminal,
    User,
)
from .clock import gen_no, now_sim
from .commands import send_command
from .effects import build_profile_snapshot
from .errors import BadRequestError, ConflictError, NotFoundError, UnprocessableError
from .tasks import cancel_tasks, complete_tasks, open_task

# 允许通过 API 注入的故障键 -> 指令 fault_mode
_FAULT_KEY_MAP = {
    "prepare_fault": ("prepare_profile", "reject_incompatible"),
    "stop_fault": ("stop_credential", "lose_response"),
}


def lock_number_by_msisdn(db: Session, msisdn: str) -> PhoneNumber:
    number = db.execute(
        select(PhoneNumber).where(PhoneNumber.msisdn == msisdn).with_for_update()
    ).scalar_one_or_none()
    if number is None:
        raise NotFoundError("NUMBER_NOT_FOUND", f"号码 {msisdn} 不存在（虚构资料）")
    return number


def build_planned(now, strategy: str) -> tuple[dict, object, object]:
    """返回 planned 结构与预计中断起止时刻。"""
    if strategy == Strategy.PREPARE_FIRST:
        steps = [
            {"key": "prepare", "kind": CommandKind.PREPARE_PROFILE,
             "start_min": 0, "end_min": 2, "duration_min": 2,
             "label": "准备未激活新配置"},
            {"key": "stop", "kind": CommandKind.STOP_CREDENTIAL,
             "start_min": 2, "end_min": 3, "duration_min": 1,
             "label": "停用旧凭据并获确认"},
            {"key": "enable", "kind": CommandKind.ENABLE_CREDENTIAL,
             "start_min": 3, "end_min": 4, "duration_min": 1,
             "label": "启用新凭据并获确认"},
        ]
        outage_start, outage_end = now + timedelta(minutes=3), now + timedelta(minutes=4)
        outage_label = "第 3~4 模拟分钟"
    else:
        steps = [
            {"key": "stop", "kind": CommandKind.STOP_CREDENTIAL,
             "start_min": 0, "end_min": 1, "duration_min": 1,
             "label": "先停用旧凭据并获确认"},
            {"key": "prepare", "kind": CommandKind.PREPARE_PROFILE,
             "start_min": 1, "end_min": 3, "duration_min": 2,
             "label": "准备未激活新配置（客户无服务）"},
            {"key": "enable", "kind": CommandKind.ENABLE_CREDENTIAL,
             "start_min": 3, "end_min": 4, "duration_min": 1,
             "label": "启用新凭据并获确认"},
        ]
        outage_start, outage_end = now + timedelta(minutes=1), now + timedelta(minutes=4)
        outage_label = "第 1~4 模拟分钟"
    planned = {
        "total_min": 4,
        "outage_label": outage_label,
        "steps": [
            {**s,
             "planned_start_sim": (now + timedelta(minutes=s["start_min"])).isoformat(sep=" "),
             "planned_end_sim": (now + timedelta(minutes=s["end_min"])).isoformat(sep=" ")}
            for s in steps
        ],
    }
    return planned, outage_start, outage_end


def create_order(db: Session, user: User, body) -> ReplaceOrder:
    # 先取单号（锁 sim_clock），再锁号码行，保持全局一致的加锁顺序 clock -> number
    order_no = gen_no(db, "RO")
    now = now_sim(db)

    number = lock_number_by_msisdn(db, body.msisdn)

    # 客户只能给自己的号码申请
    if user.role == "customer" and user.customer_id != number.customer_id:
        raise ApiError_forbidden()

    # 同一号码同时只允许一张在办单：行锁 + 状态检查（另有部分唯一索引兜底）
    existing = db.execute(
        select(ReplaceOrder).where(
            ReplaceOrder.number_id == number.id,
            ReplaceOrder.status.in_([s.value for s in OPEN_ORDER_STATUSES]),
        )
    ).scalars().first()
    if existing is not None:
        raise ConflictError(
            "ORDER_IN_PROGRESS",
            f"号码 {body.msisdn} 已有在办换卡单 {existing.order_no}（状态 {existing.status}），"
            f"不能两人同时办理；请继续原单或等其办结。",
            {"existing_order_id": existing.id, "existing_order_no": existing.order_no},
        )

    reason = body.reason
    if reason not in [r.value for r in Reason]:
        raise BadRequestError("BAD_REASON", f"未知换卡原因：{reason}")

    old_in_hand = bool(body.old_card_in_hand)
    strategy = body.strategy
    if reason == Reason.LOST.value:
        # 报失必须先挂失，绝不允许用“先准备”让遗失卡继续有效
        if strategy == Strategy.PREPARE_FIRST.value:
            raise UnprocessableError(
                "LOST_MUST_REPORT_FIRST",
                "客户报失时必须先挂失并停用旧凭据，不能采用先准备新配置的正常升级路径保留遗失卡。",
            )
        strategy = Strategy.STOP_FIRST.value
    elif strategy is None:
        strategy = (Strategy.PREPARE_FIRST.value if old_in_hand
                    else Strategy.STOP_FIRST.value)

    if strategy == Strategy.PREPARE_FIRST.value and not old_in_hand:
        raise UnprocessableError(
            "OLD_CARD_NOT_IN_HAND",
            "旧卡不在本人手中时不能先准备后停旧，请选择先停旧路径。",
        )
    if strategy not in [s.value for s in Strategy]:
        raise BadRequestError("BAD_STRATEGY", f"未知办理时序：{strategy}")

    terminal = None
    if body.terminal_model:
        terminal = db.execute(
            select(Terminal).where(Terminal.model == body.terminal_model)
        ).scalar_one_or_none()
        if terminal is None:
            raise NotFoundError("TERMINAL_NOT_FOUND", f"终端机型 {body.terminal_model} 不在虚构终端库")

    # 找到当前有效旧凭据
    old_cred = db.execute(
        select(Credential).where(
            Credential.number_id == number.id,
            Credential.status == CredentialStatus.ACTIVE,
        )
    ).scalar_one_or_none()

    planned, outage_start_p, outage_end_p = build_planned(now, strategy)

    order = ReplaceOrder(
        order_no=order_no, number_id=number.id, customer_id=number.customer_id,
        terminal_id=terminal.id if terminal else None,
        reason=reason, old_card_in_hand=old_in_hand, strategy=strategy,
        status=OrderStatus.SUBMITTED,
        old_credential_id=old_cred.id if old_cred else None,
        fault_flags=body.fault_flags or {},
        t0_sim=now, planned=planned,
        outage_start_planned_sim=outage_start_p,
        outage_end_planned_sim=outage_end_p,
        failure_contact=(
            f"营业：{settings.support_clerk}；网络：{settings.support_network}；"
            f"热线：{settings.support_hotline}"
        ),
        remark=body.remark,
    )
    db.add(order)
    db.flush()

    iv = IdentityVerification(order_id=order.id, result="pending",
                              channel="证件信息核验(虚构适配器)")
    db.add(iv)
    open_task(db, assignee=TaskAssignee.CUSTOMER, type_="identity_verify",
              title="完成身份核验",
              detail="输入与开户资料一致的证件号，虚构身份适配器即时返回结果。",
              order_id=order.id, action_hint="verify")
    db.flush()
    return order


def ApiError_forbidden():  # 小辅助，避免顶部循环命名
    from .errors import ApiError
    return ApiError(403, "NUMBER_NOT_OWNED", "客户只能为本人名下号码申请换卡")


def verify_identity(db: Session, order: ReplaceOrder, id_number: str,
                    channel: str | None = None) -> IdentityVerification:
    customer = db.get(Customer, order.customer_id)
    iv = db.query(IdentityVerification).filter_by(order_id=order.id).order_by(
        IdentityVerification.id.desc()).first()
    now = now_sim(db)
    if iv is None:
        iv = IdentityVerification(order_id=order.id)
        db.add(iv)
    if channel:
        iv.channel = channel

    fault_fail = (order.fault_flags or {}).get("identity") == "fail"
    passed = (not fault_fail) and id_number.strip().upper() == customer.id_number.upper()
    iv.verified_at_sim = now
    if passed:
        iv.result = "pass"
        iv.score = 98
        iv.raw = {"adapter": "fictional-id-gateway", "match": True,
                  "checks": ["姓名一致", "证件号一致", "活体分数 96.4"]}
        if order.status in (OrderStatus.SUBMITTED, OrderStatus.IDENTITY_FAILED):
            order.status = OrderStatus.PENDING_ASSIGNMENT
            complete_tasks(db, order_id=order.id, types=["identity_verify"])
            open_task(db, assignee=TaskAssignee.CLERK, type_="assign_card",
                      title="身份核验通过，分配兼容新卡",
                      detail="先核对外形，再由网络准备配置时校验 profile/5G 深层兼容性。",
                      order_id=order.id, action_hint="assign")
    else:
        iv.result = "fail"
        iv.score = 41
        iv.raw = {"adapter": "fictional-id-gateway", "match": False,
                  "reason": "证件号与开户资料不一致（或演练故障注入）"}
        order.status = OrderStatus.IDENTITY_FAILED
    db.flush()
    return iv


def assign_card(db: Session, order: ReplaceOrder, *, card_id: int | None = None,
                card_no: str | None = None, auto: bool = False) -> SimCard:
    if order.status not in (OrderStatus.PENDING_ASSIGNMENT, OrderStatus.PREPARE_FAILED):
        raise ConflictError(
            "ORDER_NOT_ASSIGNABLE",
            f"订单当前状态 {order.status} 不允许分配/改分卡（需待分配或准备失败）。",
        )

    stmt = select(SimCard).where(SimCard.status == CardStatus.IN_STOCK)
    if card_id is not None:
        stmt = stmt.where(SimCard.id == card_id)
    elif card_no:
        stmt = stmt.where(SimCard.card_no == card_no)
    elif auto:
        # 按终端外形自动挑一张通用兼容卡（避开已知 legacy_v1）
        if order.terminal_id:
            terminal = db.get(Terminal, order.terminal_id)
            stmt = stmt.where(SimCard.form_factor == terminal.required_form_factor)
            if terminal and terminal.requires_5g:
                stmt = stmt.where(SimCard.network_gen == "5G")
        stmt = stmt.where(SimCard.profile_type == "universal_v2")
    else:
        raise BadRequestError("CARD_REQUIRED", "请指定 card_id/card_no 或 auto=true")

    card = db.execute(stmt.order_by(SimCard.id).with_for_update()).scalars().first()
    if card is None:
        raise ConflictError("NO_COMPATIBLE_CARD", "虚构卡库中没有满足条件的在库卡")

    # 外形兼容性是营业台必须拦截的第一层
    if order.terminal_id:
        terminal = db.get(Terminal, order.terminal_id)
        if terminal and card.form_factor != terminal.required_form_factor:
            raise UnprocessableError(
                "CARD_FORM_FACTOR_INCOMPATIBLE",
                f"卡 {card.card_no} 外形 {card.form_factor} 与终端 {terminal.model} "
                f"要求的 {terminal.required_form_factor} 不匹配，不能分配。",
            )

    # 若之前分过卡（准备失败改分），旧卡在 effects 中通常已释放；这里兜底释放
    if order.assigned_card_id and order.assigned_card_id != card.id:
        old = db.get(SimCard, order.assigned_card_id)
        if old and old.reserved_order_id == order.id:
            old.status = CardStatus.IN_STOCK
            old.reserved_order_id = None

    card.status = CardStatus.RESERVED
    card.reserved_order_id = order.id
    order.assigned_card_id = card.id
    if order.outage_start_actual_sim is not None:
        # 先停旧路径下准备失败后改分卡：旧凭据仍处于已停用状态
        order.status = OrderStatus.OLD_STOPPED
    else:
        order.status = OrderStatus.CARD_ASSIGNED
    complete_tasks(db, order_id=order.id, types=["assign_card", "reassign_card"])
    open_task(db, assignee=TaskAssignee.NETWORK, type_="prepare_profile",
              title="下发准备配置指令（模拟 2 分钟）",
              detail="制卡/配置完成只代表未激活配置就绪，不会产生第二个 active 凭据。",
              order_id=order.id, action_hint="prepare")
    db.flush()
    return card


# ---------------------------------------------------------------- 网络动作

def _fault_for(order: ReplaceOrder, key: str) -> str:
    flags = order.fault_flags or {}
    mapped = _FAULT_KEY_MAP.get(key)
    if mapped and flags.get(key):
        return mapped[1]
    return "normal"


def action_report_loss(db: Session, order: ReplaceOrder, user: User):
    if order.reason != Reason.LOST.value:
        raise BadRequestError("NOT_LOSS_ORDER", "只有报失场景需要挂失指令")
    if order.status not in (OrderStatus.PENDING_ASSIGNMENT, OrderStatus.CARD_ASSIGNED,
                            OrderStatus.SUBMITTED, OrderStatus.LOSS_REPORTING):
        raise ConflictError("LOSS_NOT_ALLOWED", f"状态 {order.status} 不允许挂失")
    cmd = send_command(
        db, order=order, kind=CommandKind.REPORT_LOSS, number_id=order.number_id,
        payload={"msisdn": db.get(PhoneNumber, order.number_id).msisdn,
                 "reason": order.reason}, duration_min=0,
    )
    # 挂失即时成功（虚构适配器同步受理）
    from .simulator import adapter_execute
    from .effects import apply_outcome
    truth = adapter_execute(db, cmd)
    cmd.adapter_outcome = truth
    cmd.adapter_executed_at_sim = now_sim(db)
    apply_outcome(db, cmd, truth)
    number = db.get(PhoneNumber, order.number_id)
    number.service_status = "loss_reported"
    open_task(db, assignee=TaskAssignee.NETWORK, type_="stop_old",
              title="挂失已受理，下发停旧凭据指令",
              detail="报失路径必须先挂失再停旧，之后才能准备/启用新卡。",
              order_id=order.id, action_hint="stop")
    db.flush()
    return cmd


def action_prepare(db: Session, order: ReplaceOrder, user: User):
    # 按办理时序强制动作顺序，防止 API 调用把两条路径混成一团
    if order.strategy == Strategy.PREPARE_FIRST.value:
        if order.status != OrderStatus.CARD_ASSIGNED.value:
            raise ConflictError("PREPARE_NOT_ALLOWED",
                                f"先准备路径在分卡后才能准备配置，当前状态 {order.status}")
    else:
        if order.status != OrderStatus.OLD_STOPPED.value:
            raise ConflictError("PREPARE_NOT_ALLOWED",
                                f"先停旧路径必须在旧凭据停用确认后才能准备配置，当前状态 {order.status}")
    if order.reason == Reason.LOST.value:
        _require_loss_before_sensitive(db, order)

    number = db.get(PhoneNumber, order.number_id)
    card = db.get(SimCard, order.assigned_card_id) if order.assigned_card_id else None

    # 每次准备产生新的“凭据身份”，初始 preparing；成功后才是 prepared
    cred_no = gen_no(db, "CRED")
    cred = Credential(
        credential_code=f"IMSI-NEW-{cred_no[-6:]}",
        number_id=order.number_id, card_id=card.id if card else None,
        order_id=order.id, status=CredentialStatus.PREPARING,
        profile_snapshot=build_profile_snapshot(number),
        profile_plan_version=number.plan_version,
        created_at_sim=now_sim(db),
    )
    db.add(cred)
    db.flush()
    order.new_credential_id = cred.id
    order.status = OrderStatus.PREPARING

    cmd = send_command(
        db, order=order, kind=CommandKind.PREPARE_PROFILE,
        credential_id=cred.id, number_id=order.number_id,
        payload={"card_no": card.card_no if card else None,
                 "iccid": card.iccid if card else None,
                 "profile_snapshot_plan_version": number.plan_version},
        fault_mode=_fault_for(order, "prepare_fault"),
    )
    db.flush()
    return cmd


def _require_loss_before_sensitive(db: Session, order: ReplaceOrder) -> None:
    """报失单在准备配置前，必须已有成功的挂失指令。"""
    loss_cmd = db.execute(
        select(NetworkCommand).where(
            NetworkCommand.order_id == order.id,
            NetworkCommand.kind == CommandKind.REPORT_LOSS,
            NetworkCommand.status == CommandStatus.SUCCEEDED,
        )
    ).scalar_one_or_none()
    if loss_cmd is None:
        raise UnprocessableError("LOSS_FIRST_REQUIRED", "报失号码必须先成功挂失，再办理后续指令")


def action_stop(db: Session, order: ReplaceOrder, user: User):
    # 两条路径的停旧时机不同：先准备路径必须等新配置就绪；先停旧路径分卡/挂失后即可停
    if order.strategy == Strategy.PREPARE_FIRST.value:
        if order.status != OrderStatus.PREPARED.value:
            raise ConflictError("STOP_NOT_ALLOWED",
                                f"先准备路径必须在新配置就绪(prepared)后才能停旧，当前 {order.status}")
    else:
        if order.status not in (OrderStatus.CARD_ASSIGNED.value,
                                OrderStatus.LOSS_REPORTED.value):
            raise ConflictError("STOP_NOT_ALLOWED",
                                f"先停旧路径需在分卡/挂失后停旧，当前状态 {order.status}")
    if order.reason == Reason.LOST.value:
        loss_cmd = db.execute(
            select(NetworkCommand).where(
                NetworkCommand.order_id == order.id,
                NetworkCommand.kind == CommandKind.REPORT_LOSS,
                NetworkCommand.status == "succeeded",
            )
        ).scalar_one_or_none()
        if loss_cmd is None:
            raise UnprocessableError("LOSS_FIRST_REQUIRED", "客户报失：必须先挂失成功，才能停旧")

    old_cred = db.get(Credential, order.old_credential_id) if order.old_credential_id else None
    order.status = OrderStatus.STOPPING_OLD
    cmd = send_command(
        db, order=order, kind=CommandKind.STOP_CREDENTIAL,
        credential_id=old_cred.id if old_cred else None,
        number_id=order.number_id,
        payload={"credential": old_cred.credential_code if old_cred else None},
        fault_mode=_fault_for(order, "stop_fault"),
    )
    db.flush()
    return cmd


def action_enable(db: Session, order: ReplaceOrder, user: User):
    if order.status not in (OrderStatus.OLD_STOPPED, OrderStatus.ENABLE_REJECTED):
        raise ConflictError(
            "ENABLE_NOT_ALLOWED",
            f"状态 {order.status} 不允许启用新配置；必须在旧凭据已确认停用后。"
            + ("停旧结果未知时请先查询原指令。" if order.status == OrderStatus.STOP_OLD_UNKNOWN else ""),
        )
    if order.status == OrderStatus.STOP_OLD_UNKNOWN:  # 双保险
        raise ConflictError("STOP_UNKNOWN_MUST_QUERY", "停旧结果未知，必须先查询原指令")
    cred = db.get(Credential, order.new_credential_id) if order.new_credential_id else None
    if cred is None or cred.status not in (CredentialStatus.PREPARED,):
        raise ConflictError("NEW_PROFILE_NOT_READY", "没有已就绪的未激活新配置，不能启用")

    order.status = OrderStatus.ENABLING_NEW
    cmd = send_command(
        db, order=order, kind=CommandKind.ENABLE_CREDENTIAL,
        credential_id=cred.id, number_id=order.number_id,
        payload={"credential": cred.credential_code,
                 "profile_plan_version": cred.profile_plan_version},
    )
    db.flush()
    return cmd


def action_refresh(db: Session, order: ReplaceOrder, user: User):
    if order.status != OrderStatus.ENABLE_REJECTED:
        raise ConflictError("REFRESH_NOT_ALLOWED",
                            f"状态 {order.status} 无需/不能刷新配置（仅启用因套餐版本过期被拒后）")
    cred = db.get(Credential, order.new_credential_id)
    cmd = send_command(
        db, order=order, kind=CommandKind.REFRESH_PROFILE,
        credential_id=cred.id if cred else None, number_id=order.number_id,
        payload={"target_plan_version": db.get(PhoneNumber, order.number_id).plan_version},
    )
    db.flush()
    return cmd


def query_command(db: Session, command_id: int, user: User):
    from ..models import NetworkCommand
    original = db.get(NetworkCommand, command_id)
    if original is None:
        raise NotFoundError("COMMAND_NOT_FOUND", "指令不存在")
    if original.status != CommandStatus.UNKNOWN:
        raise ConflictError("QUERY_ONLY_UNKNOWN",
                            f"只有结果未知的指令需要查询原指令；当前状态 {original.status}")
    # 不允许用“重发/新开”替代查询：这里显式生成 QUERY_COMMAND 关联原指令
    cmd = send_command(
        db, order=db.get(ReplaceOrder, original.order_id),
        kind=CommandKind.QUERY_COMMAND, number_id=original.number_id,
        relates_to_id=original.id,
        payload={"query_command_no": original.command_no,
                 "idempotency_key_original": original.idempotency_key},
    )
    db.flush()
    return cmd


def reassign_card_guard(db: Session, order: ReplaceOrder):
    """停旧结果未知时，禁止任何“另开第二张卡”式操作。"""
    from ..models import NetworkCommand
    unknown_stop = db.execute(
        select(NetworkCommand).where(
            NetworkCommand.order_id == order.id,
            NetworkCommand.kind == CommandKind.STOP_CREDENTIAL,
            NetworkCommand.status == CommandStatus.UNKNOWN,
        )
    ).scalar_one_or_none()
    if unknown_stop is not None:
        raise ConflictError(
            "STOP_UNKNOWN_QUERY_FIRST",
            "旧卡停用指令结果未知：必须先查询原指令确认真实结果，"
            "不能按超时当失败去开第二张卡或重新制卡。",
            {"command_no": unknown_stop.command_no},
        )


# ---------------------------------------------------------------- 激活核验/结清

def run_probes(db: Session, order: ReplaceOrder, user: User) -> dict:
    if order.status not in (OrderStatus.ACTIVE_PENDING_CONFIRM, OrderStatus.CONFIRMED):
        raise ConflictError("NOT_ACTIVE_YET", f"状态 {order.status} 尚不能做激活核验")
    now = now_sim(db)
    # 虚构终端/网络探测适配器：全部给出可复核的探测值
    checks = {
        "probed_at_sim": now.isoformat(sep=" "),
        "signal": {"item": "无线信号注册", "ok": True, "detail": "RSRP -72dBm，已注册 5G SA（虚构）"},
        "data": {"item": "数据连通", "ok": True, "detail": "ping 虚构网关 26ms，HTTP 204 探测成功"},
        "voice": {"item": "高清通话", "ok": True, "detail": "VoLTE 呼叫 1008611(虚构) 接通，语音清晰"},
        "sms": {"item": "短信收发", "ok": True, "detail": "向虚构网关发送/接收回执成功"},
        "ready": True,
    }
    order.activation_checks = checks
    db.flush()
    return checks


def confirm_activation(db: Session, order: ReplaceOrder, user: User) -> ReplaceOrder:
    if order.status != OrderStatus.ACTIVE_PENDING_CONFIRM:
        raise ConflictError("CONFIRM_NOT_ALLOWED",
                            f"状态 {order.status} 不允许客户确认（需网络启用成功待确认）")
    checks = order.activation_checks or {}
    if not checks.get("ready"):
        raise UnprocessableError("PROBES_REQUIRED",
                                 "请先运行激活核验探测，确认信号/上网/通话/短信正常后再确认")
    order.status = OrderStatus.CONFIRMED
    order.confirmed_at_sim = now_sim(db)
    complete_tasks(db, order_id=order.id, types=["confirm_activation"])
    amount = 20 if order.reason == Reason.LOST.value else 10
    st = Settlement(
        order_id=order.id, amount=amount,
        items=[{"name": "挂失补卡服务费" if order.reason == Reason.LOST.value else "SIM 换卡工本费",
                "amount": amount}],
        status="pending", created_at_sim=now_sim(db),
    )
    db.add(st)
    open_task(db, assignee=TaskAssignee.CUSTOMER, type_="settle",
              title="结清换卡费用", detail=f"客户已确认新卡可用，待结清 ¥{amount}。",
              order_id=order.id, action_hint="settle")
    db.flush()
    return order


def settle_order(db: Session, order: ReplaceOrder, channel: str) -> Settlement:
    if order.status != OrderStatus.CONFIRMED:
        raise ConflictError("SETTLE_NOT_ALLOWED", "客户确认新卡实际可用后才能结清")
    st = db.query(Settlement).filter_by(order_id=order.id).one()
    st.status = "paid"
    st.paid_at_sim = now_sim(db)
    st.items = list(st.items or []) + [{"name": f"支付渠道：{channel}", "amount": 0}]
    order.status = OrderStatus.SETTLED
    complete_tasks(db, order_id=order.id, types=["settle"])
    db.flush()
    return st


# ---------------------------------------------------------------- 受控退换

def direct_rollback(db: Session, order: ReplaceOrder):
    """一键恢复旧凭据在任何已启新场景都不允许。"""
    if order.status in (OrderStatus.ACTIVE_PENDING_CONFIRM, OrderStatus.CONFIRMED,
                        OrderStatus.SETTLED, OrderStatus.EXCHANGE_REQUESTED,
                        OrderStatus.EXCHANGED):
        raise ConflictError(
            "USE_CONTROLLED_EXCHANGE",
            "新凭据已启用，不能一键恢复旧凭据（旧凭据已停用）。"
            "如客户要取消，请发起受控退换，由网络台停退新配置并走重新发卡流程。",
        )
    # 未启新前允许直接取消
    order.status = OrderStatus.CANCELLED
    if order.assigned_card_id:
        card = db.get(SimCard, order.assigned_card_id)
        if card and card.reserved_order_id == order.id:
            card.status = CardStatus.IN_STOCK
            card.reserved_order_id = None
    complete_tasks(db, order_id=order.id,
                   types=["assign_card", "reassign_card", "prepare_profile", "stop_old",
                          "enable_new", "query_stop", "refresh_profile", "confirm_activation"])
    db.flush()
    return order


def request_exchange(db: Session, order: ReplaceOrder, reason: str, user: User):
    from ..models import ExchangeCase
    if order.status not in (OrderStatus.ACTIVE_PENDING_CONFIRM, OrderStatus.CONFIRMED,
                            OrderStatus.SETTLED):
        raise ConflictError("EXCHANGE_NOT_ALLOWED",
                            "只有新卡已启用后的取消才需要受控退换；未启新可直接取消订单。")
    case_no = gen_no(db, "EX")
    case = ExchangeCase(order_id=order.id, case_no=case_no, reason=reason,
                        status="requested", created_at_sim=now_sim(db))
    db.add(case)
    order.status = OrderStatus.EXCHANGE_REQUESTED
    # 客户不再确认可用性：原确认待办作废，改走受控退换待办
    cancel_tasks(db, order_id=order.id, types=["confirm_activation", "settle"])
    open_task(db, assignee=TaskAssignee.NETWORK, type_="exchange_stop_new",
              title="受控退换：停退新凭据",
              detail="不得恢复旧凭据；停退新凭据后由营业重新发卡/处理退款。",
              order_id=order.id, action_hint="complete_exchange")
    db.flush()
    return case


def complete_exchange(db: Session, case_id: int, user: User):
    from ..models import ExchangeCase
    case = db.get(ExchangeCase, case_id)
    if case is None:
        raise NotFoundError("EXCHANGE_NOT_FOUND", "退换单不存在")
    if case.status != "requested":
        raise ConflictError("EXCHANGE_NOT_OPEN", f"退换单状态 {case.status}")
    order = db.get(ReplaceOrder, case.order_id)
    cred = db.get(Credential, order.new_credential_id)
    if cred:
        cred.status = CredentialStatus.RETURNED
        cred.stopped_at_sim = now_sim(db)
    if order.assigned_card_id:
        card = db.get(SimCard, order.assigned_card_id)
        if card:
            card.status = CardStatus.QUARANTINE
            card.reserved_order_id = None
    case.status = "completed"
    case.completed_at_sim = now_sim(db)
    order.status = OrderStatus.EXCHANGED
    complete_tasks(db, order_id=order.id, types=["exchange_stop_new"])
    open_task(db, assignee=TaskAssignee.CLERK, type_="exchange_reissue",
              title="受控退换完成：为客户重新发卡或退款",
              detail="旧凭据保持停用不可恢复；如需继续服务请新建换卡单并分配新卡。",
              order_id=order.id, action_hint="assign")
    db.flush()
    return case
