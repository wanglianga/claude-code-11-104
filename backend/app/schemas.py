"""请求体模型。"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class LoginIn(BaseModel):
    username: str
    password: str


class OrderCreateIn(BaseModel):
    msisdn: str
    reason: str
    strategy: str | None = None  # 不传则按 reason / old_card_in_hand 决定
    old_card_in_hand: bool = True
    terminal_model: str | None = None
    remark: str | None = None
    # 演练故障注入：{"stop_fault":"lose_response", "prepare_fault":"reject_incompatible"}
    fault_flags: dict[str, Any] = Field(default_factory=dict)


class IdentityIn(BaseModel):
    id_number: str
    channel: str | None = None


class AssignCardIn(BaseModel):
    card_id: int | None = None
    card_no: str | None = None
    auto: bool = False


class TickIn(BaseModel):
    minutes: int = 1


class AutoIn(BaseModel):
    enabled: bool


class PlanChangeIn(BaseModel):
    msisdn: str
    to_plan_code: str = "PLAN_5G_299"
    approve: bool = True


class LateReceiptIn(BaseModel):
    msisdn: str
    delay_min: int = 2
    duplicate: bool = True


class FaultIn(BaseModel):
    fault_flags: dict[str, Any]


class ExchangeIn(BaseModel):
    reason: str = "客户在新卡激活后申请取消"


class SettleIn(BaseModel):
    channel: str = "虚构支付-话费账户"
