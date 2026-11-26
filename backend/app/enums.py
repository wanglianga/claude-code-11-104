"""集中定义枚举与状态集合（字符串落库，便于阅读与核对）。"""
from enum import StrEnum


class Role(StrEnum):
    CUSTOMER = "customer"
    CLERK = "clerk"          # 营业员
    NETWORK = "network"      # 网络办理员
    ADMIN = "admin"


class Reason(StrEnum):
    NORMAL_UPGRADE = "normal_upgrade"      # 正常换卡/升级，旧卡仍在手中
    TERMINAL_CHANGE = "terminal_change"  # 更换终端，需要兼容配置
    DAMAGED = "damaged"                   # 卡片损坏（旧卡可能不在手/不可用）
    LOST = "lost"                         # 报失：必须先挂失


class Strategy(StrEnum):
    PREPARE_FIRST = "prepare_first"  # 先备新配置再停旧：中断 T+3~T+4
    STOP_FIRST = "stop_first"        # 先停旧再备新：中断 T+1~T+4


class OrderStatus(StrEnum):
    SUBMITTED = "submitted"                       # 客户已提交，待营业受理/核验
    IDENTITY_FAILED = "identity_failed"
    PENDING_ASSIGNMENT = "pending_assignment"     # 身份通过，待分配卡
    CARD_ASSIGNED = "card_assigned"
    PREPARING = "preparing"                       # 配置制作中（2 分钟）
    PREPARE_FAILED = "prepare_failed"             # 新配置被拒/不兼容
    PREPARED = "prepared"                         # 未激活新配置就绪
    LOSS_REPORTING = "loss_reporting"
    LOSS_REPORTED = "loss_reported"               # 已挂失
    STOPPING_OLD = "stopping_old"
    STOP_OLD_UNKNOWN = "stop_old_unknown"         # 停旧指令结果未知
    OLD_STOPPED = "old_stopped"
    ENABLING_NEW = "enabling_new"
    ENABLE_REJECTED = "enable_rejected"           # 例如配置套餐版本过期
    ACTIVE_PENDING_CONFIRM = "active_pending_confirm"
    CONFIRMED = "confirmed"                       # 客户确认新卡实际可用
    SETTLED = "settled"                           # 已结清，流程完成
    CANCELLED = "cancelled"
    EXCHANGE_REQUESTED = "exchange_requested"     # 已启新后的受控退换中
    EXCHANGED = "exchanged"                       # 受控退换办结


# 仍在占用号码、不允许第二人同时办理的状态
OPEN_ORDER_STATUSES = {
    OrderStatus.SUBMITTED,
    OrderStatus.PENDING_ASSIGNMENT,
    OrderStatus.CARD_ASSIGNED,
    OrderStatus.PREPARING,
    OrderStatus.PREPARE_FAILED,
    OrderStatus.PREPARED,
    OrderStatus.LOSS_REPORTING,
    OrderStatus.LOSS_REPORTED,
    OrderStatus.STOPPING_OLD,
    OrderStatus.STOP_OLD_UNKNOWN,
    OrderStatus.OLD_STOPPED,
    OrderStatus.ENABLING_NEW,
    OrderStatus.ENABLE_REJECTED,
    OrderStatus.ACTIVE_PENDING_CONFIRM,
    OrderStatus.CONFIRMED,
    OrderStatus.EXCHANGE_REQUESTED,
}


class CardStatus(StrEnum):
    IN_STOCK = "in_stock"        # 虚构卡库可分配
    RESERVED = "reserved"        # 已分配/预留
    IN_USE = "in_use"            # 对应凭据已激活
    RETIRED = "retired"          # 换卡后旧卡已随旧凭据停用/作废
    RELEASED = "released"        # 异常后释放回库（仍可再分配）
    QUARANTINE = "quarantine"    # 问题卡隔离


class CredentialStatus(StrEnum):
    ACTIVE = "active"                    # 当前有效激活凭据（全局唯一约束）
    PREPARING = "preparing"
    PREPARED = "prepared"                # 制卡完成 = 未激活配置就绪
    PREPARE_REJECTED = "prepare_rejected"
    STOPPED = "stopped"                  # 旧凭据已停用
    LOSS_BLOCKED = "loss_blocked"        # 挂失停用
    RETURNED = "returned"                # 受控退换后停用/退回


class CommandKind(StrEnum):
    REPORT_LOSS = "report_loss"
    PREPARE_PROFILE = "prepare_profile"
    STOP_CREDENTIAL = "stop_credential"
    ENABLE_CREDENTIAL = "enable_credential"
    QUERY_COMMAND = "query_command"
    REFRESH_PROFILE = "refresh_profile"


class CommandStatus(StrEnum):
    QUEUED = "queued"          # 已创建，尚未下发
    SENT = "sent"              # 已发，等待回执
    SUCCEEDED = "succeeded"    # 成功
    REJECTED = "rejected"      # 被网络/适配器拒绝
    UNKNOWN = "unknown"        # 超时且未拿到回执，结果未知


class FaultMode(StrEnum):
    NORMAL = "normal"
    LOSE_RESPONSE = "lose_response"        # 执行成功但回执丢失 -> 未知
    REJECT_INCOMPATIBLE = "reject_incompatible"
    DELAY_RECEIPT = "delay_receipt"        # 回执晚到（按 delay_min 模拟）


class TaskStatus(StrEnum):
    OPEN = "open"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskAssignee(StrEnum):
    CLERK = "clerk"
    NETWORK = "network"
    CUSTOMER = "customer"


class SettlementStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"


class ExchangeStatus(StrEnum):
    REQUESTED = "requested"
    APPROVED = "approved"
    COMPLETED = "completed"
    REJECTED = "rejected"
