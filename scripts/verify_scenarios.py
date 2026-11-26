#!/usr/bin/env python3
"""号卡更换与激活办理平台 —— 五场景 + 挂失/恢复路径端到端核对脚本。

用法：
  1) 先启动后端（使用预装 PostgreSQL）：
       cd backend
       SIM_AUTO_START=0 ALLOW_RESET=1 .venv/bin/uvicorn app.main:app --port 8000
  2) 另开终端执行：
       backend/.venv/bin/python scripts/verify_scenarios.py

脚本会先调用 /api/test/reset 重建虚构数据，可重复执行。
核对：唯一激活、配置继承内容、卡库存、通信中断窗口、指令四态、待办任务、
并发换卡、不兼容、准备中套餐变更、停旧回执丢失、旧启用回执晚到。
"""
from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import httpx
import psycopg

BASE = os.getenv("VERIFY_BASE_URL", "http://127.0.0.1:8000")
PG_DSN = os.getenv(
    "VERIFY_PG_DSN",
    "host=127.0.0.1 port=5432 dbname=ccdev user=ccdev password=ccdev",
)

IDCARD = {
    "13900001111": "110101199203154321",
    "13900002222": "310104198811200042",
    "13900003333": "440305199507077718",
    "13900004444": "330106199001256624",
    "13900005555": "51010719871212331X",
    "13900006666": "420106199606068844",
    "13900007777": "120103199909091234",
}


class Report:
    def __init__(self):
        self.passed = 0
        self.failures: list[str] = []

    def check(self, name: str, cond: bool, detail: str = ""):
        if cond:
            self.passed += 1
            print(f"  \033[32mPASS\033[0m  {name}")
        else:
            self.failures.append(f"{name} :: {detail}")
            print(f"  \033[31mFAIL\033[0m  {name} -- {detail}")

    def section(self, title: str):
        print(f"\n\033[36m== {title} ==\033[0m")


rep = Report()


# ---------------------------------------------------------------- API 封装

def wait_health(timeout_s: float = 30):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        try:
            r = httpx.get(f"{BASE}/api/health", timeout=3)
            if r.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    print(f"后端不可达：{BASE}，请先启动 uvicorn（见脚本头注释 / README）")
    sys.exit(2)


def login(username: str, password: str = "test1234") -> str:
    if username == "admin":
        password = "admin123"
    r = httpx.post(f"{BASE}/api/auth/login",
                   json={"username": username, "password": password}, timeout=10)
    assert r.status_code == 200, f"登录失败 {username}: {r.status_code} {r.text}"
    return r.json()["token"]


TOK: dict[str, str] = {}


def call(method: str, path: str, who: str = "admin", json=None, ok: bool = True):
    headers = {"Authorization": f"Bearer {TOK[who]}"} if who in TOK else {}
    r = httpx.request(method, f"{BASE}/api{path}", json=json,
                      headers=headers, timeout=30)
    if ok and r.status_code >= 400:
        raise AssertionError(f"{method} {path} -> {r.status_code} {r.text}")
    return r


def reset():
    r = httpx.post(f"{BASE}/api/test/reset", timeout=60)
    assert r.status_code == 200, f"reset 失败: {r.status_code} {r.text}"


def tick(minutes: int = 1):
    return call("POST", "/sim/tick", "net", {"minutes": minutes}).json()


def order(oid: int) -> dict:
    return call("GET", f"/orders/{oid}").json()


def snapshot() -> dict:
    return call("GET", "/test/snapshot").json()


def sim_now() -> datetime:
    return datetime.fromisoformat(call("GET", "/sim").json()["now_sim"])


def off(ts: str | None, t0: datetime) -> float | None:
    if not ts:
        return None
    return (datetime.fromisoformat(ts) - t0).total_seconds() / 60.0


def find_cmd(o: dict, kind: str, status: str | None = None) -> dict | None:
    for c in reversed(o["commands"]):
        if c["kind"] == kind and (status is None or c["status"] == status):
            return c
    return None


def create(msisdn: str, who: str = "admin", **kw) -> httpx.Response:
    body = {"msisdn": msisdn, "reason": kw.pop("reason", "normal_upgrade"), **kw}
    return call("POST", "/orders", who, body, ok=False)


def onboard(msisdn: str, *, strategy: str | None = None, reason: str = "normal_upgrade",
            card: str | None = None, auto_card: bool = True, who_assign: str = "clerk",
            **create_kw) -> dict:
    """创建 -> 身份核验 -> 分卡，返回最新订单。"""
    r = create(msisdn, reason=reason, strategy=strategy, **create_kw)
    assert r.status_code == 200, f"建单失败: {r.status_code} {r.text}"
    o = r.json()
    call("POST", f"/orders/{o['id']}/verify-identity",
         "cust_" + msisdn, {"id_number": IDCARD[msisdn]})
    o = order(o["id"])
    if card:
        call("POST", f"/orders/{o['id']}/assign-card", who_assign, {"card_no": card})
    elif auto_card:
        call("POST", f"/orders/{o['id']}/assign-card", who_assign, {"auto": True})
    return order(o["id"])


def prepare_wait(oid: int, ticks: int = 2):
    call("POST", f"/orders/{oid}/prepare", "net")
    tick(ticks)
    return order(oid)


def stop_wait(oid: int, ticks: int = 1):
    call("POST", f"/orders/{oid}/stop", "net")
    tick(ticks)
    return order(oid)


def enable_wait(oid: int, ticks: int = 1):
    call("POST", f"/orders/{oid}/enable", "net")
    tick(ticks)
    return order(oid)


def confirm_settle(oid: int, msisdn: str):
    call("POST", f"/orders/{oid}/probes", "net")
    call("POST", f"/orders/{oid}/confirm", "cust_" + msisdn)
    call("POST", f"/orders/{oid}/settle", "cust_" + msisdn,
         {"channel": "虚构支付-话费账户"})
    return order(oid)


def number_snap(snap: dict, msisdn: str) -> dict:
    return next(n for n in snap["numbers"] if n["msisdn"] == msisdn)


def open_task_types(oid: int | None = None) -> set[str]:
    s = snapshot()
    return {t["type"] for t in s["open_tasks"] if oid is None or t["order_id"] == oid}


# ---------------------------------------------------------------- 主流程

def main():
    wait_health()
    print(f"目标后端 {BASE}；重置虚构数据 ...")
    reset()

    for key, username in [("admin", "admin"), ("clerk", "clerk01"), ("net", "net01")]:
        TOK[key] = login(username)
    for m in IDCARD:
        TOK["cust_" + m] = login(m)

    # 关闭自动走钟，保证断言只由显式 tick 驱动
    call("POST", "/sim/auto", "net", {"enabled": False})

    snap0 = snapshot()
    rep.check("种子：7 个号码各有 1 个 active 凭据",
              all(len(n["active_credential_ids"]) == 1 for n in snap0["numbers"]),
              str([(n["msisdn"], n["active_credential_ids"]) for n in snap0["numbers"]]))
    rep.check("种子：全局 active 凭据总数=7", snap0["active_credential_total"] == 7,
              str(snap0["active_credential_total"]))
    rep.check("种子：卡库 13 张在库 + 7 张在用",
              snap0["card_counts"].get("in_stock") == 13
              and snap0["card_counts"].get("in_use") == 7,
              str(snap0["card_counts"]))

    # ============================================================
    rep.section("场景1 两人同时给同一号码换卡（并发）+ 先准备正常路径")
    m1 = "13900001111"
    before1 = number_snap(snap0, m1)
    t0 = sim_now()

    def concurrent_create(i):
        who = ["admin", "clerk", "cust_" + m1][i % 3]
        return create(m1, who=who, remark=f"concurrent-{i}")

    with ThreadPoolExecutor(max_workers=8) as ex:
        responses = list(ex.map(concurrent_create, range(8)))
    ok200 = [r for r in responses if r.status_code == 200]
    conflicts = [r for r in responses if r.status_code == 409]
    rep.check("并发 8 个建单请求：恰好 1 个成功", len(ok200) == 1,
              f"200={len(ok200)} 409={len(conflicts)} "
              f"other={[r.status_code for r in responses if r.status_code not in (200,409)]}")
    rep.check("其余全部 409 ORDER_IN_PROGRESS",
              len(conflicts) == 7
              and all(r.json()["error"]["code"] == "ORDER_IN_PROGRESS" for r in conflicts),
              str([r.json().get("error", {}).get("code") for r in conflicts]))

    oid1 = ok200[0].json()["id"]
    o1 = order(oid1)
    rep.check("默认时序：旧卡在手 -> prepare_first", o1["strategy"] == "prepare_first",
              o1["strategy"])
    rep.check("预计中断窗口=第3~4分钟",
              off(o1["outage_start_planned_sim"], t0) == 3
              and off(o1["outage_end_planned_sim"], t0) == 4,
              f"{o1['outage_start_planned_sim']} ~ {o1['outage_end_planned_sim']}")

    call("POST", f"/orders/{oid1}/verify-identity", "cust_" + m1,
         {"id_number": IDCARD[m1]})
    call("POST", f"/orders/{oid1}/assign-card", "clerk", {"auto": True})
    o1 = order(oid1)
    card1_id = o1["assigned_card_id"]
    rep.check("分卡后卡状态 reserved", o1["card"]["status"] == "reserved", o1["card"]["status"])

    call("POST", f"/orders/{oid1}/prepare", "net")
    tick(1)
    o1 = order(oid1)
    rep.check("准备 1 分钟时仍在 preparing（指令已发）", o1["status"] == "preparing", o1["status"])
    tick(1)
    o1 = order(oid1)
    prep_cmd = find_cmd(o1, "prepare_profile")
    rep.check("准备满 2 分钟：指令 succeeded，订单 prepared（未激活就绪）",
              prep_cmd["status"] == "succeeded" and o1["status"] == "prepared",
              f"{prep_cmd['status']}/{o1['status']}")
    rep.check("制卡完成≠激活：新凭据 prepared，active 仍是旧凭据",
              o1["new_credential"]["status"] == "prepared"
              and len(number_snap(snapshot(), m1)["active_credential_ids"]) == 1
              and number_snap(snapshot(), m1)["active_credential_ids"][0] == o1["old_credential_id"],
              "")

    stop_wait(oid1)
    o1 = order(oid1)
    rep.check("停旧成功后 old_stopped，中断起点=T+3",
              o1["status"] == "old_stopped" and off(o1["outage_start_actual_sim"], t0) == 3,
              f"{o1['status']}, start off={off(o1['outage_start_actual_sim'], t0)}")
    enable_wait(oid1)
    o1 = order(oid1)
    rep.check("启新成功：active_pending_confirm，中断终点=T+4",
              o1["status"] == "active_pending_confirm"
              and off(o1["outage_end_actual_sim"], t0) == 4,
              f"{o1['status']}, end={off(o1['outage_end_actual_sim'], t0)}")

    o1 = confirm_settle(oid1, m1)
    rep.check("客户确认并结清 -> settled", o1["status"] == "settled", o1["status"])
    rep.check("结算单 paid 且金额 10 元",
              o1["settlement"]["status"] == "paid" and o1["settlement"]["amount"] == 10,
              str(o1["settlement"]))

    s1 = snapshot()
    n1 = number_snap(s1, m1)
    rep.check("唯一激活：恰好 1 个 active 且为新凭据",
              n1["active_credential_ids"] == [o1["new_credential_id"]],
              str(n1["active_credential_ids"]))
    rep.check("旧凭据详情=stopped，旧实体卡 retired",
              o1["old_credential"]["status"] == "stopped",
              o1["old_credential"]["status"])
    rep.check("新卡 in_use", o1["card"]["status"] == "in_use", o1["card"]["status"])
    rep.check("配置继承：套餐/权限/账期写入 profile",
              o1["new_credential"]["profile_snapshot"]["plan_code"] == "PLAN_5G_199"
              and "5G" in o1["new_credential"]["profile_snapshot"]["permissions"]
              and "国际漫游" in o1["new_credential"]["profile_snapshot"]["permissions"]
              and o1["new_credential"]["profile_snapshot"]["billing_cycle_day"] == 6,
              str(o1["new_credential"]["profile_snapshot"]))
    rep.check("换卡不重置权益/账期：用量与账期日不变",
              (n1["cycle_data_used_mb"], n1["cycle_voice_used_min"],
               n1["benefits_used_count"], n1["billing_cycle_day"], n1["plan_version"])
              == (before1["cycle_data_used_mb"], before1["cycle_voice_used_min"],
                  before1["benefits_used_count"], 6, 1),
              str(n1))
    rep.check("本单无遗留 open 任务", oid1 not in [t["order_id"] for t in s1["open_tasks"]],
              str([t["title"] for t in s1["open_tasks"] if t["order_id"] == oid1]))

    # ============================================================
    rep.section("场景2 新配置不兼容（先准备路径）：旧卡不受影响，改分兼容卡")
    m2 = "13900002222"
    o2 = onboard(m2, strategy="prepare_first", card="K0001",
                  terminal_model="Mate70-X")
    rep.check("K0001 外形 nano 可分配（深层兼容在准备时校验）",
              o2["card"]["card_no"] == "K0001" and o2["status"] == "card_assigned", o2["status"])
    call("POST", f"/orders/{o2['id']}/prepare", "net")
    tick(2)
    o2 = order(o2["id"])
    pc = find_cmd(o2, "prepare_profile")
    rep.check("准备指令被拒 PROFILE_INCOMPATIBLE，订单 prepare_failed",
              pc["status"] == "rejected" and pc["response_code"] == "PROFILE_INCOMPATIBLE"
              and o2["status"] == "prepare_failed",
              f"{pc['status']}/{pc.get('response_code')}/{o2['status']}")
    rep.check("失败时旧卡仍 active、通信未中断（无 outage 实际值）",
              o2["old_credential"]["status"] == "active"
              and o2["outage_start_actual_sim"] is None
              and o2["outage_end_actual_sim"] is None,
              f"{o2['old_credential']['status']}")
    rep.check("生成营业改分卡待办 reassign_card",
              "reassign_card" in open_task_types(o2["id"]), str(open_task_types(o2["id"])))
    k1 = next(c for c in snapshot()["cards"] if c["card_no"] == "K0001")
    rep.check("不兼容卡释放回库 in_stock（库存不丢）", k1["status"] == "in_stock", k1["status"])

    call("POST", f"/orders/{o2['id']}/assign-card", "clerk", {"card_no": "K0003"})
    o2 = prepare_wait(o2["id"], 2)
    rep.check("改分 K0003 后准备成功", o2["status"] == "prepared", o2["status"])
    stop_wait(o2["id"])
    enable_wait(o2["id"])
    o2 = confirm_settle(o2["id"], m2)
    rep.check("场景2 办结 settled", o2["status"] == "settled", o2["status"])
    rep.check("K0003 in_use，K0001 仍在库",
              o2["card"]["card_no"] == "K0003" and o2["card"]["status"] == "in_use"
              and next(c for c in snapshot()["cards"] if c["card_no"] == "K0001")["status"]
              == "in_stock", "")

    # ============================================================
    rep.section("场景3 准备中套餐获批变更：配置过期 -> 刷新 -> 继承新套餐")
    m3 = "13900003333"
    before3 = number_snap(snapshot(), m3)
    o3 = onboard(m3, strategy="prepare_first", auto_card=True)
    call("POST", f"/orders/{o3['id']}/prepare", "net")
    # 准备指令已发、2 分钟制作中：此刻批准套餐变更
    chg = call("POST", "/scenarios/plan-change", "clerk",
                {"msisdn": m3, "to_plan_code": "PLAN_5G_299"}).json()
    rep.check("套餐获批：plan_version 1->2，账期日/用量不变",
              chg["before"]["plan_version"] == 1 and chg["after"]["plan_version"] == 2
              and chg["before"]["billing_cycle_day"] == chg["after"]["billing_cycle_day"] == 15
              and chg["before"]["cycle_data_used_mb"] == chg["after"]["cycle_data_used_mb"] == 8888,
              str(chg))
    tick(2)
    o3 = order(o3["id"])
    rep.check("准备完成但快照是旧套餐版本且标记 stale",
              o3["new_credential"]["status"] == "prepared"
              and o3["new_credential"]["profile_plan_version"] == 1
              and o3["new_credential"]["profile_stale"] is True,
              str(o3["new_credential"]))
    stop_wait(o3["id"])
    call("POST", f"/orders/{o3['id']}/enable", "net")
    tick(1)
    o3 = order(o3["id"])
    ec = find_cmd(o3, "enable_credential", "rejected")
    rep.check("启用被拒 PROFILE_PLAN_STALE，订单 enable_rejected",
              ec is not None and ec["response_code"] == "PROFILE_PLAN_STALE"
              and o3["status"] == "enable_rejected",
              str(ec and ec["response_code"]) + "/" + o3["status"])
    rep.check("生成网络刷新配置待办 refresh_profile",
              "refresh_profile" in open_task_types(o3["id"]), "")
    call("POST", f"/orders/{o3['id']}/refresh", "net")
    tick(1)
    o3 = order(o3["id"])
    rep.check("刷新后快照升级到 v299/v2，stale 清除，回到可启用",
              o3["new_credential"]["profile_plan_version"] == 2
              and o3["new_credential"]["profile_stale"] is False
              and o3["new_credential"]["profile_snapshot"]["plan_code"] == "PLAN_5G_299"
              and "机场贵宾厅" in o3["new_credential"]["profile_snapshot"]["permissions"]
              and o3["status"] == "old_stopped",
              f"{o3['new_credential']['profile_plan_version']}/{o3['status']}")
    call("POST", f"/orders/{o3['id']}/enable", "net")
    tick(1)
    o3 = confirm_settle(o3["id"], m3)
    n3 = number_snap(snapshot(), m3)
    rep.check("场景3 办结且唯一 active 为新凭据",
              o3["status"] == "settled"
              and n3["active_credential_ids"] == [o3["new_credential_id"]], "")
    rep.check("套餐变更没有重置已用权益或改变账期",
              n3["cycle_data_used_mb"] == before3["cycle_data_used_mb"] == 8888
              and n3["cycle_voice_used_min"] == 45
              and n3["benefits_used_count"] == 3
              and n3["billing_cycle_day"] == 15,
              str(n3))

    # ============================================================
    rep.section("场景4 停旧成功但响应丢失：unknown -> 先查原指令，禁止开第二张卡")
    m4 = "13900004444"
    # 报失 + prepare_first 必须被拒绝（先在无在办单时验证）
    rbad = create(m4, reason="lost", strategy="prepare_first")
    rep.check("报失却选先准备 -> 422 LOST_MUST_REPORT_FIRST",
              rbad.status_code == 422
              and rbad.json()["error"]["code"] == "LOST_MUST_REPORT_FIRST",
              f"{rbad.status_code} {rbad.text[:200]}")

    t4 = sim_now()
    o4 = onboard(m4, reason="lost", strategy="stop_first",
                 fault_flags={"stop_fault": "lose_response"})
    rep.check("报失单强制 stop_first", o4["strategy"] == "stop_first", o4["strategy"])
    # 未挂失先停旧 -> 拒绝
    rstop = call("POST", f"/orders/{o4['id']}/stop", "net", ok=False)
    rep.check("未挂失先停旧 -> 422 LOSS_FIRST_REQUIRED",
              rstop.status_code == 422
              and rstop.json()["error"]["code"] == "LOSS_FIRST_REQUIRED", rstop.text[:200])
    call("POST", f"/orders/{o4['id']}/report-loss", "net")
    o4 = order(o4["id"])
    rep.check("挂失指令成功，状态 loss_reported",
              find_cmd(o4, "report_loss", "succeeded") is not None
              and o4["status"] == "loss_reported", o4["status"])

    call("POST", f"/orders/{o4['id']}/stop", "net")
    tick(1)  # 到期：适配器真实成功，但回执丢失
    o4 = order(o4["id"])
    sc = find_cmd(o4, "stop_credential", "sent")
    rep.check("回执丢失当刻：指令仍 sent（不能猜结果）", sc is not None, "")
    tick(1)  # 超过 unknown 宽限
    o4 = order(o4["id"])
    sc = find_cmd(o4, "stop_credential", "unknown")
    rep.check("宽限后指令 unknown，订单 stop_old_unknown",
              sc is not None and o4["status"] == "stop_old_unknown",
              f"{sc and sc['status']}/{o4['status']}")
    rep.check("待办明确要求 query_stop", "query_stop" in open_task_types(o4["id"]), "")

    ren = call("POST", f"/orders/{o4['id']}/enable", "net", ok=False)
    rep.check("unknown 时禁止启用新卡", ren.status_code == 409, str(ren.status_code))
    rasg = call("POST", f"/orders/{o4['id']}/assign-card", "clerk",
                {"card_no": "K0009"}, ok=False)
    rep.check("unknown 时禁止改分/开第二张卡 STOP_UNKNOWN_QUERY_FIRST",
              rasg.status_code == 409
              and rasg.json()["error"]["code"] == "STOP_UNKNOWN_QUERY_FIRST",
              f"{rasg.status_code} {rasg.text[:200]}")

    q = call("POST", f"/commands/{sc['id']}/query", "net").json()
    rep.check("生成关联原指令的 query_command", q["kind"] == "query_command"
              and q["relates_to_id"] == sc["id"], "")
    tick(1)
    o4 = order(o4["id"])
    sc2 = find_cmd(o4, "stop_credential", "succeeded")
    qc = find_cmd(o4, "query_command", "succeeded")
    rep.check("查询确认后：原停旧指令 succeeded，查询指令 succeeded，订单 old_stopped",
              sc2 is not None and qc is not None and o4["status"] == "old_stopped",
              o4["status"])
    rep.check("中断起点按网络真实执行时刻=T+1（而非查询时刻 T+2）",
              off(o4["outage_start_actual_sim"], t4) == 1,
              str(off(o4["outage_start_actual_sim"], t4)))

    # stop_first：查询占用了 T+2~T+3，之后准备 2 分钟、启用 1 分钟
    call("POST", f"/orders/{o4['id']}/prepare", "net")
    tick(2)
    o4 = order(o4["id"])
    rep.check("查询澄清后准备成功并回到 old_stopped(可启用)",
              o4["status"] == "old_stopped", o4["status"])
    call("POST", f"/orders/{o4['id']}/enable", "net")
    tick(1)
    o4 = order(o4["id"])
    rep.check("中断终点=T+6（未知+查询拉长了实际中断）",
              o4["status"] == "active_pending_confirm"
              and off(o4["outage_end_actual_sim"], t4) == 6,
              f"{o4['status']} end off={off(o4['outage_end_actual_sim'], t4)}")
    o4 = confirm_settle(o4["id"], m4)
    rep.check("场景4 办结", o4["status"] == "settled", o4["status"])

    # ============================================================
    rep.section("场景5 旧启用回执晚到（重复/迟到）：忽略且不改变唯一 active")
    m5 = "13900005555"
    late = call("POST", "/scenarios/late-receipt", "net",
                {"msisdn": m5, "delay_min": 6, "duplicate": True}).json()
    rep.check("已编排旧启用指令的 6 分钟后迟到回执",
              late["command_no"].startswith("CMD-SEED-EN"), late["command_no"])
    t5 = sim_now()
    o5 = onboard(m5, strategy="prepare_first")
    call("POST", f"/orders/{o5['id']}/prepare", "net")
    tick(2)
    stop_wait(o5["id"])
    enable_wait(o5["id"])
    o5 = order(o5["id"])
    new_id = o5["new_credential_id"]
    rep.check("新凭据 active 且全号码唯一",
              o5["status"] == "active_pending_confirm"
              and number_snap(snapshot(), m5)["active_credential_ids"] == [new_id], "")
    # 走到 T+6 让迟到回执投递（建单/核验/分卡不耗时，t5 即 T0）
    elapsed = 4
    tick(max(0, 6 - elapsed + 1))  # 再补 3 个 tick 到 T+7
    s5 = snapshot()
    late_rcpts = [r for r in s5["receipts"] if r["command_no"] == late["command_no"]
                  and r.get("ignore_reason") == "duplicate_late_receipt_ignored"]
    rep.check("迟到/重复旧启用回执被留痕但忽略(applied=false)",
              len(late_rcpts) >= 1, str([r for r in s5["receipts"]
                                         if r["command_no"] == late["command_no"]]))
    n5 = number_snap(s5, m5)
    rep.check("迟到回执未复活旧凭据：active 仍是新凭据且唯一",
              n5["active_credential_ids"] == [new_id], str(n5["active_credential_ids"]))
    rep.check("旧凭据保持 stopped",
              next(c for c in n5["credentials"] if c["id"] == o5["old_credential_id"])["status"]
              == "stopped", "")

    # 已启新后不能一键恢复旧凭据，只能受控退换
    rrb = call("POST", f"/orders/{o5['id']}/cancel", "admin", ok=False)
    rep.check("已启新后直接取消/回滚 -> 409 USE_CONTROLLED_EXCHANGE",
              rrb.status_code == 409
              and rrb.json()["error"]["code"] == "USE_CONTROLLED_EXCHANGE", rrb.text[:200])
    ex = call("POST", f"/orders/{o5['id']}/exchange", "cust_" + m5,
              {"reason": "客户改变主意"}).json()
    call("POST", f"/exchange/{ex['case_id']}/complete", "net")
    s5b = snapshot()
    n5b = number_snap(s5b, m5)
    rep.check("受控退换后新凭据 returned、卡 quarantine、订单 exchanged",
              n5b["active_credential_ids"] == []
              and next(c for c in n5b["credentials"] if c["id"] == new_id)["status"]
              == "returned"
              and next(c for c in s5b["cards"] if c["id"] == o5["assigned_card_id"])["status"]
              == "quarantine", "")
    rep.check("受控退换也没有恢复旧凭据（旧凭据仍 stopped）",
              next(c for c in n5b["credentials"] if c["id"] == o5["old_credential_id"])["status"]
              == "stopped", "")

    # ============================================================
    rep.section("场景6 客户报失路径：先挂失，名义中断窗口仍为第1~4分钟")
    m6 = "13900006666"
    t6 = sim_now()
    o6 = onboard(m6, reason="lost")  # 不传 strategy，后端强制 stop_first
    rep.check("报失建单即强制 stop_first", o6["strategy"] == "stop_first", o6["strategy"])
    call("POST", f"/orders/{o6['id']}/report-loss", "net")
    stop_wait(o6["id"])
    o6 = order(o6["id"])
    rep.check("停旧成功，旧凭据 loss_blocked，中断起点 T+1",
              o6["old_credential"]["status"] == "loss_blocked"
              and off(o6["outage_start_actual_sim"], t6) == 1,
              f"{o6['old_credential']['status']}/{off(o6['outage_start_actual_sim'], t6)}")
    call("POST", f"/orders/{o6['id']}/prepare", "net")
    tick(2)
    enable_wait(o6["id"])
    o6 = order(o6["id"])
    rep.check("无异常时时序精确：中断终点 T+4（第1~4分钟）",
              off(o6["outage_end_actual_sim"], t6) == 4,
              str(off(o6["outage_end_actual_sim"], t6)))
    o6 = confirm_settle(o6["id"], m6)
    rep.check("挂失补卡结算 20 元并办结",
              o6["status"] == "settled" and o6["settlement"]["amount"] == 20,
              str(o6["settlement"]))

    # ============================================================
    rep.section("场景7 先停旧路径下准备失败：客户已在中断中，恢复动作更紧迫")
    m7 = "13900007777"
    t7 = sim_now()
    o7 = onboard(m7, strategy="stop_first", card="K0001", terminal_model="iPhone-16")
    stop_wait(o7["id"])
    o7 = order(o7["id"])
    rep.check("先停旧：T+1 起中断，旧凭据 stopped",
              off(o7["outage_start_actual_sim"], t7) == 1
              and o7["old_credential"]["status"] == "stopped", "")
    call("POST", f"/orders/{o7['id']}/prepare", "net")
    tick(2)
    o7 = order(o7["id"])
    rep.check("准备被拒 prepare_failed，但中断已经发生且尚无终点",
              o7["status"] == "prepare_failed"
              and o7["outage_start_actual_sim"] is not None
              and o7["outage_end_actual_sim"] is None, o7["status"])
    rep.check("客户无服务中存在待办 reassign_card",
              "reassign_card" in open_task_types(o7["id"]), "")
    call("POST", f"/orders/{o7['id']}/assign-card", "clerk", {"card_no": "K0008"})
    o7 = order(o7["id"])
    rep.check("改分后状态恢复 old_stopped（不会要求重新停旧）",
              o7["status"] == "old_stopped", o7["status"])
    call("POST", f"/orders/{o7['id']}/prepare", "net")
    tick(2)
    enable_wait(o7["id"])
    o7 = confirm_settle(o7["id"], m7)
    rep.check("恢复后办结；因失败重试，实际中断终点晚于 T+4（=T+6）",
              o7["status"] == "settled"
              and off(o7["outage_end_actual_sim"], t7) == 6,
              f"end={off(o7['outage_end_actual_sim'], t7)}")

    # ============================================================
    rep.section("数据库级不变量：部分唯一索引拒绝第二个 active 凭据")
    with psycopg.connect(PG_DSN) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute("select id from ss_phone_numbers where msisdn=%s", (m1,))
            nid = cur.fetchone()[0]
            cur.execute("select count(*) from ss_credentials where number_id=%s and status='active'",
                        (nid,))
            cnt = cur.fetchone()[0]
            rep.check("SQL 直查：场景1号码 active 凭据数=1", cnt == 1, str(cnt))
            try:
                cur.execute(
                    "insert into ss_credentials "
                    "(credential_code, number_id, status, profile_snapshot, "
                    " profile_plan_version, profile_stale, created_at_sim) "
                    "values ('IMSI-ROGUE-999', %s, 'active', '{}', 1, false, now())",
                    (nid,),
                )
                conn.commit()
                rep.check("部分唯一索引拒绝第二个 active", False, "插入竟然成功")
            except psycopg.errors.UniqueViolation:
                conn.rollback()
                rep.check("部分唯一索引拒绝第二个 active（UniqueViolation）", True)

            cur.execute("select count(*) from ss_replace_orders "
                        "where status not in ('settled','cancelled','exchanged')")
            open_orders = cur.fetchone()[0]
            # 种子公共待办不影响；在办单应为 0（所有场景单均终态）
            rep.check("所有场景单已到终态：无在办换卡单", open_orders == 0, str(open_orders))

    # ============================================================
    rep.section("卡库存与全局任务核对")
    s_end = snapshot()
    total_cards = sum(s_end["card_counts"].values())
    rep.check("卡库存总数守恒=20（7 旧卡 + 13 新卡）", total_cards == 20,
              str(s_end["card_counts"]))
    rep.check("没有遗留 reserved 卡", s_end["card_counts"].get("reserved", 0) == 0,
              str(s_end["card_counts"]))
    rep.check("7 张旧卡全部 retired",
              s_end["card_counts"].get("retired") == 7, str(s_end["card_counts"]))
    rep.check("新卡 6 张 in_use（A/B/C/D/F/G；E 走受控退换）",
              s_end["card_counts"].get("in_use") == 6, str(s_end["card_counts"]))
    rep.check("quarantine=1（受控退换卡）",
              s_end["card_counts"].get("quarantine") == 1, str(s_end["card_counts"]))
    rep.check("其余 6 张在库（含被拒后释放的 K0001 与未使用卡）",
              s_end["card_counts"].get("in_stock") == 6, str(s_end["card_counts"]))
    # 仍 open 的任务：已结清单必须干净；受控退换单按设计保留 exchange_reissue
    open_by_order: dict[int, set[str]] = {}
    for t in s_end["open_tasks"]:
        if t["order_id"] is not None:
            open_by_order.setdefault(t["order_id"], set()).add(t["type"])
    settled_ids = {o["id"] for o in s_end["orders"] if o["status"] == "settled"}
    dirty_settled = {i: ts for i, ts in open_by_order.items() if i in settled_ids}
    rep.check("所有已结清订单无遗留 open 任务", not dirty_settled, str(dirty_settled))
    rep.check("受控退换单保留唯一后续任务 exchange_reissue（仍需办理）",
              open_by_order.get(o5["id"]) == {"exchange_reissue"},
              str(open_by_order.get(o5["id"])))
    rep.check("其余 open 任务仅为无订单的种子公共任务",
              all(oid == o5["id"] for oid in open_by_order),
              str(open_by_order))

    print("\n" + "=" * 64)
    if rep.failures:
        print(f"\033[31m验证未通过：{len(rep.failures)} 项失败，{rep.passed} 项通过\033[0m")
        for f in rep.failures:
            print(" - " + f)
        sys.exit(1)
    print(f"\033[32mALL SCENARIO CHECKS PASSED：{rep.passed} 项断言全部通过\033[0m")
    sys.exit(0)


if __name__ == "__main__":
    main()
