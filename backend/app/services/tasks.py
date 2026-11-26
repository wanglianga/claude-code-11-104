"""待办任务辅助。"""
from __future__ import annotations

from sqlalchemy.orm import Session

from ..models import TaskItem
from .clock import now_sim


def open_task(db: Session, *, assignee: str, type_: str, title: str,
              detail: str = "", order_id: int | None = None,
              action_hint: str | None = None) -> TaskItem:
    t = TaskItem(
        order_id=order_id, assignee_role=assignee, type=type_, title=title,
        detail=detail, status="open", action_hint=action_hint,
        created_at_sim=now_sim(db),
    )
    db.add(t)
    db.flush()
    return t


def complete_tasks(db: Session, *, order_id: int, types: list[str]) -> int:
    rows = (db.query(TaskItem)
            .filter(TaskItem.order_id == order_id, TaskItem.type.in_(types),
                    TaskItem.status == "open").all())
    ts = now_sim(db)
    for t in rows:
        t.status = "done"
        t.done_at_sim = ts
    return len(rows)


def cancel_tasks(db: Session, *, order_id: int, types: list[str]) -> int:
    rows = (db.query(TaskItem)
            .filter(TaskItem.order_id == order_id, TaskItem.type.in_(types),
                    TaskItem.status == "open").all())
    ts = now_sim(db)
    for t in rows:
        t.status = "cancelled"
        t.done_at_sim = ts
    return len(rows)
