"""模拟时钟与单号生成：所有业务时刻都取自 ss_sim_clock，保证可回放、可核对。"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import SimClock

SEED_NOW = datetime(2026, 11, 26, 9, 0, 0)


def get_clock(db: Session, lock: bool = False) -> SimClock:
    stmt = select(SimClock).where(SimClock.id == 1)
    if lock:
        stmt = stmt.with_for_update()
    clock = db.execute(stmt).scalar_one()
    return clock


def now_sim(db: Session) -> datetime:
    return get_clock(db).now_sim


def advance(db: Session, minutes: int) -> SimClock:
    clock = get_clock(db, lock=True)
    clock.now_sim = clock.now_sim + timedelta(minutes=minutes)
    db.flush()
    return clock


def gen_no(db: Session, prefix: str) -> str:
    clock = get_clock(db, lock=True)
    clock.seq += 1
    return f"{prefix}{clock.now_sim:%Y%m%d}-{clock.seq:04d}"
