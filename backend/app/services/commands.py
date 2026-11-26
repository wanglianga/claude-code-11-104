"""网络指令原语：创建即“已发”，预计/到期/未知时刻一次算清。"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from ..config import settings
from ..models import NetworkCommand, ReplaceOrder
from .clock import gen_no, now_sim

DURATIONS = {
    "report_loss": 0,
    "prepare_profile": 2,   # 模拟准备配置需 2 分钟
    "stop_credential": 1,   # 停旧需 1 分钟获确认
    "enable_credential": 1, # 启新需 1 分钟获确认
    "query_command": 1,
    "refresh_profile": 1,
}


def send_command(
    db: Session,
    *,
    order: ReplaceOrder | None,
    kind: str,
    credential_id: int | None = None,
    number_id: int | None = None,
    relates_to_id: int | None = None,
    payload: dict | None = None,
    fault_mode: str = "normal",
    duration_min: int | None = None,
    receipt_delay_min: int = 0,
) -> NetworkCommand:
    now = now_sim(db)
    duration = DURATIONS[kind] if duration_min is None else duration_min
    command_no = gen_no(db, "CMD")
    cmd = NetworkCommand(
        command_no=command_no,
        idempotency_key=f"idem-{command_no}",
        order_id=order.id if order else None,
        number_id=number_id if number_id is not None else (order.number_id if order else 0),
        credential_id=credential_id,
        relates_to_id=relates_to_id,
        kind=kind,
        status="sent",
        request_payload=payload or {},
        fault_mode=fault_mode,
        receipt_delay_min=receipt_delay_min,
        duration_min=duration,
        attempt=1,
        queued_at_sim=now,
        sent_at_sim=now,
        estimated_complete_at_sim=now + timedelta(minutes=duration),
        due_at_sim=now + timedelta(minutes=duration),
        unknown_at_sim=now + timedelta(minutes=duration + settings.unknown_grace_min),
    )
    db.add(cmd)
    db.flush()
    return cmd
