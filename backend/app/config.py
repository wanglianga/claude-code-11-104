"""应用配置：全部可由环境变量覆盖。

本地开发默认连接容器内预装的 PostgreSQL（ccdev/ccdev）。
"""
import os


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    app_name: str = "号卡更换与激活办理平台（虚构演练系统）"
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://ccdev:ccdev@127.0.0.1:5432/ccdev",
    )
    # 允许 /api/test/reset 一键重建虚构数据（演示/验证用，生产应关闭）
    allow_reset: bool = _bool("ALLOW_RESET", True)
    # 启动后模拟时钟是否自动走动；验证脚本会先关闭它
    sim_auto_start: bool = _bool("SIM_AUTO_START", True)
    # 自动模式下，多少真实毫秒推进 1 个模拟分钟
    sim_tick_real_ms: int = int(os.getenv("SIM_TICK_REAL_MS", "2500"))
    # 停旧指令超过预计完成时刻多少模拟分钟仍无回执 -> 结果未知
    unknown_grace_min: int = int(os.getenv("UNKNOWN_GRACE_MIN", "1"))
    # 失败后客户联系口径（虚构）
    support_clerk: str = "营业值班经理 王岚 工号 B002（营业厅 1 号台 / 分机 8001）"
    support_network: str = "网络值班调度 陈工 工号 N001（网络办理台 / 分机 9100）"
    support_hotline: str = "服务监督热线 400-000-1004（虚构）"


settings = Settings()
