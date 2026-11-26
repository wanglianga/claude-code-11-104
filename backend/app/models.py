"""数据库模型。

身份边界：客户(customers) / 号码(phone_numbers) / 实体卡(sim_cards) /
终端(terminals) / 激活凭据(credentials) 各有独立身份，不互相替代。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class User(Base):
    __tablename__ = "ss_users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password: Mapped[str] = mapped_column(String(128))  # 仅演练用明文/弱哈希
    display_name: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(16))
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("ss_customers.id"), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Customer(Base):
    __tablename__ = "ss_customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    id_type: Mapped[str] = mapped_column(String(32), default="居民身份证(虚构)")
    id_number: Mapped[str] = mapped_column(String(64))  # 虚构证件号
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    contact_phone: Mapped[str | None] = mapped_column(String(32), nullable=True)


class Plan(Base):
    __tablename__ = "ss_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(64))
    data_mb: Mapped[int] = mapped_column(Integer, default=0)
    voice_min: Mapped[int] = mapped_column(Integer, default=0)
    # 已确认的业务权限，例如 ["5G","VoLTE","国际漫游"]
    permissions: Mapped[list] = mapped_column(JSON, default=list)
    monthly_fee: Mapped[int] = mapped_column(Integer, default=0)  # 分/元？用元整数
    version: Mapped[int] = mapped_column(Integer, default=1)


class Terminal(Base):
    __tablename__ = "ss_terminals"

    id: Mapped[int] = mapped_column(primary_key=True)
    model: Mapped[str] = mapped_column(String(64), unique=True)
    brand: Mapped[str] = mapped_column(String(64))
    required_form_factor: Mapped[str] = mapped_column(String(16), default="nano")
    requires_5g: Mapped[bool] = mapped_column(Boolean, default=False)
    required_profile_type: Mapped[str] = mapped_column(String(32), default="universal_v2")


class PhoneNumber(Base):
    __tablename__ = "ss_phone_numbers"

    id: Mapped[int] = mapped_column(primary_key=True)
    msisdn: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("ss_customers.id"), index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("ss_plans.id"))
    plan_version: Mapped[int] = mapped_column(Integer, default=1)
    billing_cycle_day: Mapped[int] = mapped_column(Integer, default=1)  # 账期日，换卡不得改变
    service_status: Mapped[str] = mapped_column(String(24), default="in_service")

    # 本期已用权益（挂在号码/订阅上，不挂在卡或凭据上，换卡不得清零）
    cycle_data_used_mb: Mapped[int] = mapped_column(Integer, default=0)
    cycle_voice_used_min: Mapped[int] = mapped_column(Integer, default=0)
    benefits_used_count: Mapped[int] = mapped_column(Integer, default=0)

    plan: Mapped[Plan] = relationship()


class BenefitLedger(Base):
    """已使用权益流水：用于核对换卡前后已用权益不被重置。"""

    __tablename__ = "ss_benefit_ledger"

    id: Mapped[int] = mapped_column(primary_key=True)
    number_id: Mapped[int] = mapped_column(ForeignKey("ss_phone_numbers.id"), index=True)
    benefit: Mapped[str] = mapped_column(String(48))
    amount: Mapped[int] = mapped_column(Integer, default=1)
    memo: Mapped[str] = mapped_column(String(128), default="")
    used_at_sim: Mapped[datetime] = mapped_column(DateTime)


class PlanChangeRequest(Base):
    """套餐变更：可在配置准备中获批，用来检验配置继承规则。"""

    __tablename__ = "ss_plan_change_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    number_id: Mapped[int] = mapped_column(ForeignKey("ss_phone_numbers.id"), index=True)
    from_plan_id: Mapped[int] = mapped_column(ForeignKey("ss_plans.id"))
    to_plan_id: Mapped[int] = mapped_column(ForeignKey("ss_plans.id"))
    status: Mapped[str] = mapped_column(String(16), default="requested")  # requested/approved/rejected
    requested_at_sim: Mapped[datetime] = mapped_column(DateTime)
    approved_at_sim: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SimCard(Base):
    __tablename__ = "ss_sim_cards"

    id: Mapped[int] = mapped_column(primary_key=True)
    iccid: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    card_no: Mapped[str] = mapped_column(String(32), unique=True)  # 卡背面短号
    form_factor: Mapped[str] = mapped_column(String(16), default="nano")  # nano/micro/standard/esim
    network_gen: Mapped[str] = mapped_column(String(8), default="5G")      # 4G/5G
    profile_type: Mapped[str] = mapped_column(String(32), default="universal_v2")
    status: Mapped[str] = mapped_column(String(16), default="in_stock", index=True)
    # 当前被哪张订单预留/占用（不设强外键约束也可，这里显式记录）
    reserved_order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stock_batch: Mapped[str] = mapped_column(String(32), default="BATCH-DEFAULT")


class Credential(Base):
    """激活凭据：一个号码同一时刻至多一个 status='active'（见部分唯一索引）。"""

    __tablename__ = "ss_credentials"
    __table_args__ = (
        Index(
            "ux_ss_credentials_one_active",
            "number_id",
            unique=True,
            postgresql_where="status = 'active'",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    credential_code: Mapped[str] = mapped_column(String(64), unique=True)  # 虚构 IMSI/凭据号
    number_id: Mapped[int] = mapped_column(ForeignKey("ss_phone_numbers.id"), index=True)
    card_id: Mapped[int | None] = mapped_column(ForeignKey("ss_sim_cards.id"), nullable=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("ss_replace_orders.id"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="preparing", index=True)

    # 配置内容快照：必须继承已确认套餐与业务权限
    profile_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    profile_plan_version: Mapped[int] = mapped_column(Integer, default=1)
    profile_stale: Mapped[bool] = mapped_column(Boolean, default=False)

    original_enable_command_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at_sim: Mapped[datetime] = mapped_column(DateTime)
    prepared_at_sim: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    activated_at_sim: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    stopped_at_sim: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class IdentityVerification(Base):
    __tablename__ = "ss_identity_verifications"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("ss_replace_orders.id"), index=True)
    channel: Mapped[str] = mapped_column(String(32), default="证件+人脸(虚构适配器)")
    result: Mapped[str] = mapped_column(String(16), default="pending")  # pass/fail/pending
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    verified_at_sim: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ReplaceOrder(Base):
    __tablename__ = "ss_replace_orders"
    __table_args__ = (
        # 同一号码只允许存在一张“在办”换卡单的应用层兜底线索（部分唯一索引）。
        # 终态：settled/cancelled/exchanged。
        Index(
            "ux_ss_orders_one_open_per_number",
            "number_id",
            unique=True,
            postgresql_where="status NOT IN ('settled','cancelled','exchanged')",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_no: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    number_id: Mapped[int] = mapped_column(ForeignKey("ss_phone_numbers.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("ss_customers.id"), index=True)
    terminal_id: Mapped[int | None] = mapped_column(ForeignKey("ss_terminals.id"), nullable=True)

    reason: Mapped[str] = mapped_column(String(24))
    old_card_in_hand: Mapped[bool] = mapped_column(Boolean, default=True)
    strategy: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(32), default="submitted", index=True)

    clerk_id: Mapped[int | None] = mapped_column(ForeignKey("ss_users.id"), nullable=True)
    network_operator_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assigned_card_id: Mapped[int | None] = mapped_column(ForeignKey("ss_sim_cards.id"), nullable=True)
    new_credential_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    old_credential_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # 场景故障注入：{"stop_fault":"lose_response", ...}
    fault_flags: Mapped[dict] = mapped_column(JSON, default=dict)

    # 计划时间（模拟时刻）与相对 T0 的分钟偏移
    t0_sim: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    planned: Mapped[dict] = mapped_column(JSON, default=dict)

    # 通信中断窗口
    outage_start_planned_sim: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    outage_end_planned_sim: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    outage_start_actual_sim: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    outage_end_actual_sim: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # 客户确认的可用性探测结果
    activation_checks: Mapped[dict] = mapped_column(JSON, default=dict)
    confirmed_at_sim: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    failure_contact: Mapped[str | None] = mapped_column(Text, nullable=True)
    remark: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class NetworkCommand(Base):
    __tablename__ = "ss_network_commands"

    id: Mapped[int] = mapped_column(primary_key=True)
    command_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(80), unique=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("ss_replace_orders.id"), nullable=True, index=True)
    number_id: Mapped[int] = mapped_column(ForeignKey("ss_phone_numbers.id"), index=True)
    credential_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    relates_to_id: Mapped[int | None] = mapped_column(ForeignKey("ss_network_commands.id"), nullable=True)

    kind: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)

    request_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    response_code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    response_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    fault_mode: Mapped[str] = mapped_column(String(32), default="normal")
    receipt_delay_min: Mapped[int] = mapped_column(Integer, default=0)

    duration_min: Mapped[int] = mapped_column(Integer, default=1)  # 模拟处理时长
    attempt: Mapped[int] = mapped_column(Integer, default=0)

    queued_at_sim: Mapped[datetime] = mapped_column(DateTime)
    sent_at_sim: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    estimated_complete_at_sim: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    due_at_sim: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    unknown_at_sim: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at_sim: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # 适配器侧的“网络真实结果”，回执丢失时平台本地状态可能仍是 unknown
    adapter_outcome: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    adapter_executed_at_sim: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CommandReceipt(Base):
    """回执流水（含迟到/重复回执），全部留痕。"""

    __tablename__ = "ss_command_receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_no: Mapped[str] = mapped_column(String(48), unique=True)
    command_no: Mapped[str] = mapped_column(String(40), index=True)
    original_command_no: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    outcome: Mapped[str] = mapped_column(String(16))  # succeeded/rejected
    code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw: Mapped[dict] = mapped_column(JSON, default=dict)
    received_at_sim: Mapped[datetime] = mapped_column(DateTime, index=True)
    applied: Mapped[bool] = mapped_column(Boolean, default=True)
    ignore_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)


class ScheduledReceipt(Base):
    """适配器计划在未来模拟时刻投递的回执（用于“旧启用回执晚到”等）。"""

    __tablename__ = "ss_scheduled_receipts"

    id: Mapped[int] = mapped_column(primary_key=True)
    deliver_at_sim: Mapped[datetime] = mapped_column(DateTime, index=True)
    command_no: Mapped[str] = mapped_column(String(40), index=True)
    original_command_no: Mapped[str | None] = mapped_column(String(40), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), default="succeeded")
    code: Mapped[str | None] = mapped_column(String(48), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    delivered: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    delivered_at_sim: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duplicate: Mapped[bool] = mapped_column(Boolean, default=False)


class TaskItem(Base):
    """各角色仍需办理的任务清单。"""

    __tablename__ = "ss_task_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("ss_replace_orders.id"), nullable=True, index=True)
    assignee_role: Mapped[str] = mapped_column(String(16), index=True)
    type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(128))
    detail: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    action_hint: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at_sim: Mapped[datetime] = mapped_column(DateTime)
    done_at_sim: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Settlement(Base):
    __tablename__ = "ss_settlements"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("ss_replace_orders.id"), unique=True)
    amount: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(8), default="CNY")
    items: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    created_at_sim: Mapped[datetime] = mapped_column(DateTime)
    paid_at_sim: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class ExchangeCase(Base):
    """已启新后取消：只能走受控退换，不能一键恢复旧凭据。"""

    __tablename__ = "ss_exchange_cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    case_no: Mapped[str] = mapped_column(String(32), unique=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("ss_replace_orders.id"), index=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="requested")
    old_credential_restorable: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(Text, default="旧凭据已停用，按受控退换流程处理，不做一键恢复。")
    created_at_sim: Mapped[datetime] = mapped_column(DateTime)
    completed_at_sim: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SimClock(Base):
    """单行表：模拟时钟。所有预计/实际时刻都以它为准。"""

    __tablename__ = "ss_sim_clock"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    now_sim: Mapped[datetime] = mapped_column(DateTime)
    auto: Mapped[bool] = mapped_column(Boolean, default=False)
    seq: Mapped[int] = mapped_column(Integer, default=0)  # 单号序列
