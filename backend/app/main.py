"""FastAPI 入口。

本地开发：uvicorn app.main:app --reload --port 8000（在 backend/ 目录、venv 中）
也可直接由本文件 python -m app.main 启动。
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError

from .config import settings
from .db import SessionLocal
from .routers.api import router as api_router
from .seed import seed_if_empty
from .services.errors import ApiError
from .services.simulator import tick as sim_tick

app = FastAPI(title=settings.app_name, version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError):
    return JSONResponse(status_code=exc.status_code,
                        content={"error": {"code": exc.code, "message": exc.message,
                                           "extra": exc.extra}})


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422,
                        content={"error": {"code": "VALIDATION_ERROR",
                                           "message": "请求参数校验失败",
                                           "extra": exc.errors()}})


@app.exception_handler(IntegrityError)
async def integrity_handler(request: Request, exc: IntegrityError):
    # 唯一激活部分索引 / 在办单部分索引的最终防线
    return JSONResponse(status_code=409,
                        content={"error": {"code": "UNIQUE_CONSTRAINT_VIOLATION",
                                           "message": "数据库唯一约束冲突（可能试图产生第二个有效激活凭据或第二张在办单）",
                                           "extra": {"orig": str(exc.orig)[:300]}}})


@app.get("/api/health")
def health():
    return {"ok": True, "app": settings.app_name}


_auto_task: asyncio.Task | None = None


async def _auto_tick_loop():
    interval = max(0.2, settings.sim_tick_real_ms / 1000.0)
    while True:
        await asyncio.sleep(interval)
        db = SessionLocal()
        try:
            from .services.clock import get_clock
            clock = get_clock(db)
            if clock.auto:
                sim_tick(db, 1)
                db.commit()
        except Exception as exc:  # noqa: BLE001 - 后台循环不能死
            db.rollback()
            print(f"[auto-tick] {type(exc).__name__}: {exc}")
        finally:
            db.close()


@app.on_event("startup")
def _startup():
    seed_if_empty()
    global _auto_task
    try:
        loop = asyncio.get_event_loop()
        _auto_task = loop.create_task(_auto_tick_loop())
    except RuntimeError:
        pass


# 前端构建产物：优先 STATIC_DIR，其次 /app/static（Docker），再其次 frontend/dist
_candidates = [
    os.getenv("STATIC_DIR"),
    "/app/static",
    str(Path(__file__).resolve().parents[2] / "frontend" / "dist"),
]
for _d in _candidates:
    if _d and Path(_d).is_dir():
        app.mount("/", StaticFiles(directory=_d, html=True), name="web")
        break


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=False)
