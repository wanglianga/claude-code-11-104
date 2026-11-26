"""极简演示认证：HMAC 签名 token，不接真实账号体系。

测试账号由 seed 写入 ss_users。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import User
from .errors import ApiError

_SECRET = "fictional-sim-swap-demo-secret"  # 仅演练系统


def _sign(payload_b64: str) -> str:
    return hmac.new(_SECRET.encode(), payload_b64.encode(), hashlib.sha256).hexdigest()[:24]


def make_token(user_id: int, role: str) -> str:
    raw = json.dumps({"uid": user_id, "role": role}, separators=(",", ":")).encode()
    p = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return f"{p}.{_sign(p)}"


def parse_token(token: str) -> dict:
    try:
        p, sig = token.split(".", 1)
        if not hmac.compare_digest(sig, _sign(p)):
            raise ValueError("bad sig")
        pad = "=" * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p + pad))
    except Exception as exc:  # noqa: BLE001
        raise ApiError(401, "INVALID_TOKEN", "登录态无效，请重新登录") from exc


def current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise ApiError(401, "NO_TOKEN", "请先登录")
    data = parse_token(authorization.split(" ", 1)[1].strip())
    user = db.get(User, data["uid"])
    if user is None:
        raise ApiError(401, "USER_NOT_FOUND", "账号不存在")
    return user


def require_roles(*roles: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise ApiError(403, "FORBIDDEN_ROLE", f"当前角色 {user.role} 无权执行该操作")
        return user

    return dep
