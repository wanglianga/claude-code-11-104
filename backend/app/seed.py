"""重建并写入全套虚构演练数据。

所有号码、证件、ICCID、回执均为虚构，不接触任何真实通信账户。
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from .config import settings
from .db import Base, SessionLocal, engine
from .enums import CardStatus, CommandKind, CommandStatus, CredentialStatus, Role, TaskAssignee, TaskStatus
from .models import (
    BenefitLedger,
    CommandReceipt,
    Credential,
    Customer,
    NetworkCommand,
    PhoneNumber,
    Plan,
    SimCard,
    SimClock,
    Terminal,
    TaskItem,
    User,
)
from .services.clock import SEED_NOW


def reset_and_seed() -> None:
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _seed(db)
        db.commit()
    finally:
        db.close()


def seed_if_empty() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(SimClock).count() == 0:
            _seed(db)
            db.commit()
    finally:
        db.close()


def _seed(db: Session) -> None:
    clock = SimClock(id=1, now_sim=SEED_NOW, auto=settings.sim_auto_start, seq=100)
    db.add(clock)

    # ---------------- 账号 ----------------
    clerk = User(
        username="clerk01", password="test1234", display_name="王岚",
        role=Role.CLERK, contact=settings.support_clerk,
    )
    netop = User(
        username="net01", password="test1234", display_name="陈工",
        role=Role.NETWORK, contact=settings.support_network,
    )
    admin = User(username="admin", password="admin123", display_name="系统管理员", role=Role.ADMIN)
    db.add_all([clerk, netop, admin])

    # ---------------- 套餐（虚构） ----------------
    plan4g = Plan(
        code="PLAN_4G_99", name="惠享4G套餐99元", data_mb=20480, voice_min=300,
        permissions=["VoLTE", "基础客服"], monthly_fee=99, version=1,
    )
    plan5g = Plan(
        code="PLAN_5G_199", name="畅享5G套餐199元", data_mb=61440, voice_min=1000,
        permissions=["5G", "VoLTE", "高清通话", "国际漫游", "云盘100G"], monthly_fee=199, version=1,
    )
    plan5gplus = Plan(
        code="PLAN_5G_299", name="尊享5G套餐299元", data_mb=122880, voice_min=2000,
        permissions=["5G", "VoLTE", "高清通话", "国际漫游", "机场贵宾厅", "云盘1T"],
        monthly_fee=299, version=1,
    )
    db.add_all([plan4g, plan5g, plan5gplus])
    db.flush()

    # ---------------- 终端（虚构机型库） ----------------
    t_huawei = Terminal(model="Mate70-X", brand="华为", required_form_factor="nano",
                        requires_5g=True, required_profile_type="universal_v2")
    t_iphone = Terminal(model="iPhone-16", brand="苹果", required_form_factor="nano",
                        requires_5g=True, required_profile_type="universal_v2")
    t_old = Terminal(model="Nokia-105", brand="诺基亚", required_form_factor="standard",
                     requires_5g=False, required_profile_type="universal_v2")
    t_watch = Terminal(model="KidsWatch-S3", brand="小星", required_form_factor="micro",
                       requires_5g=False, required_profile_type="universal_v2")
    db.add_all([t_huawei, t_iphone, t_old, t_watch])

    # ---------------- 客户 + 号码 + 在用卡/凭据 ----------------
    people = [
        # msisdn, 姓名, 证件号, 账期日, 已用流量MB, 已用通话, 已用权益次数
        ("13900001111", "李明", "110101199203154321", 6, 12345, 88, 2),
        ("13900002222", "王芳", "310104198811200042", 10, 30500, 210, 1),
        ("13900003333", "赵强", "440305199507077718", 15, 8888, 45, 3),
        ("13900004444", "孙丽", "330106199001256624", 20, 51200, 600, 5),
        ("13900005555", "周杰", "51010719871212331X", 28, 2048, 12, 0),
        ("13900006666", "吴敏", "420106199606068844", 8, 15000, 320, 2),
        ("13900007777", "郑浩", "120103199909091234", 18, 777, 9, 0),
    ]

    stock_cards: list[SimCard] = []
    old_cards: list[tuple[SimCard, Credential, NetworkCommand]] = []

    for idx, (msisdn, name, idno, bill_day, used_data, used_voice, used_benefits) in enumerate(people, start=1):
        customer = Customer(name=name, id_number=idno, verified=True,
                            contact_phone=msisdn, id_type="居民身份证(虚构)")
        db.add(customer)
        db.flush()
        user = User(username=msisdn, password="test1234", display_name=name,
                    role=Role.CUSTOMER, customer_id=customer.id,
                    contact=settings.support_hotline)
        db.add(user)

        number = PhoneNumber(
            msisdn=msisdn, customer_id=customer.id, plan_id=plan5g.id, plan_version=1,
            billing_cycle_day=bill_day, cycle_data_used_mb=used_data,
            cycle_voice_used_min=used_voice, benefits_used_count=used_benefits,
        )
        db.add(number)
        db.flush()

        # 已使用权益流水
        for k in range(used_benefits):
            db.add(BenefitLedger(
                number_id=number.id,
                benefit=["机场贵宾厅券", "云盘扩容包", "视频会员月卡"][k % 3],
                amount=1, memo="换卡前本账期已领取/使用",
                used_at_sim=SEED_NOW - timedelta(days=10 + k),
            ))

        iccid = f"898600{idx:04d}000000{idx:06d}"
        old_card = SimCard(
            iccid=iccid, card_no=f"OLD{idx:04d}", form_factor="nano",
            network_gen="5G", profile_type="universal_v2",
            status=CardStatus.IN_USE, stock_batch="BATCH-OLD",
        )
        db.add(old_card)
        db.flush()

        snapshot = {
            "msisdn": msisdn,
            "plan_code": plan5g.code,
            "plan_name": plan5g.name,
            "plan_version": 1,
            "data_mb": plan5g.data_mb,
            "voice_min": plan5g.voice_min,
            "permissions": plan5g.permissions,
            "billing_cycle_day": bill_day,
            "ki_ref": f"KI-FICTION-{idx:04d}",
            "profile_type": "universal_v2",
        }
        cred = Credential(
            credential_code=f"IMSI-FIC-{msisdn[-4:]}00",
            number_id=number.id, card_id=old_card.id, status=CredentialStatus.ACTIVE,
            profile_snapshot=snapshot, profile_plan_version=1,
            created_at_sim=SEED_NOW - timedelta(days=400),
            prepared_at_sim=SEED_NOW - timedelta(days=400, minutes=2),
            activated_at_sim=SEED_NOW - timedelta(days=400),
        )
        db.add(cred)
        db.flush()

        # 历史原始启用指令（“旧启用回执晚到”场景会重放它的迟到回执）
        enable_cmd = NetworkCommand(
            command_no=f"CMD-SEED-EN-{idx:02d}",
            idempotency_key=f"seed-enable-{idx:02d}",
            number_id=number.id, credential_id=cred.id,
            kind=CommandKind.ENABLE_CREDENTIAL, status=CommandStatus.SUCCEEDED,
            request_payload={"msisdn": msisdn, "credential": cred.credential_code, "seed": True},
            response_code="0", response_message="启用成功（历史）",
            fault_mode="normal", duration_min=1, attempt=1,
            queued_at_sim=SEED_NOW - timedelta(days=400, minutes=2),
            sent_at_sim=SEED_NOW - timedelta(days=400, minutes=2),
            estimated_complete_at_sim=SEED_NOW - timedelta(days=400, minutes=1),
            due_at_sim=SEED_NOW - timedelta(days=400, minutes=1),
            completed_at_sim=SEED_NOW - timedelta(days=400, minutes=1),
            adapter_outcome={"outcome": "succeeded", "code": "0"},
            adapter_executed_at_sim=SEED_NOW - timedelta(days=400, minutes=1),
        )
        db.add(enable_cmd)
        db.flush()
        cred.original_enable_command_id = enable_cmd.id

        db.add(CommandReceipt(
            receipt_no=f"RCP-SEED-EN-{idx:02d}",
            command_no=enable_cmd.command_no,
            outcome="succeeded", code="0", message="启用成功（历史回执）",
            raw={"seed": True}, received_at_sim=enable_cmd.completed_at_sim,
            applied=True,
        ))
        old_cards.append((old_card, cred, enable_cmd))

    # ---------------- 虚构新卡库 ----------------
    def add_card(card_no: str, iccid_tail: str, ff: str, gen: str, ptype: str, batch: str):
        c = SimCard(
            iccid=f"8986042026{iccid_tail}", card_no=card_no, form_factor=ff,
            network_gen=gen, profile_type=ptype, status=CardStatus.IN_STOCK, stock_batch=batch,
        )
        db.add(c)
        stock_cards.append(c)
        return c

    # 1 张“深层 profile 不兼容”卡：外形能分配，但网络准备配置会被拒
    add_card("K0001", "0000000001", "nano", "5G", "legacy_v1", "BATCH-2026-A")
    # 充足的通用兼容卡
    for i in range(2, 10):
        add_card(f"K{i:04d}", f"{i:010d}", "nano", "5G", "universal_v2", "BATCH-2026-A")
    add_card("K9001", "9000000001", "nano", "4G", "universal_v2", "BATCH-2026-B")
    add_card("K8001", "8000000001", "micro", "4G", "universal_v2", "BATCH-2026-C")
    add_card("K7001", "7000000001", "standard", "4G", "universal_v2", "BATCH-2026-D")
    add_card("K6001", "6000000001", "esim", "5G", "universal_v2", "BATCH-E")

    # 初始公共待办（让任务中心非空，演示“仍需办理的任务”）
    db.add(TaskItem(
        assignee_role=TaskAssignee.CLERK, type="morning_check",
        title="核对今日预约换卡名单", detail="虚构营业厅：每日开店核对预约与卡库数量。",
        status=TaskStatus.OPEN, created_at_sim=SEED_NOW, action_hint="在营业办理台受理申请",
    ))

    # 让外键顺序在 flush 时没问题
    db.flush()

    # 终端变量在上面创建但未使用引用，保留以便 seed 扩展
    _ = (t_huawei, t_iphone, t_old, t_watch, plan4g)
