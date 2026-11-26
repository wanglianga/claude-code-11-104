// 状态/类型 -> 中文文案与语义色
export const STATUS_META: Record<string, { label: string; tone: string }> = {
  submitted: { label: '已提交', tone: 'gray' },
  identity_failed: { label: '身份核验失败', tone: 'red' },
  pending_assignment: { label: '待分配新卡', tone: 'amber' },
  card_assigned: { label: '已分配卡', tone: 'blue' },
  preparing: { label: '配置准备中', tone: 'blue' },
  prepare_failed: { label: '准备失败/不兼容', tone: 'red' },
  prepared: { label: '新配置就绪(未激活)', tone: 'teal' },
  loss_reporting: { label: '挂失处理中', tone: 'amber' },
  loss_reported: { label: '已挂失', tone: 'amber' },
  stopping_old: { label: '停旧处理中', tone: 'blue' },
  stop_old_unknown: { label: '停旧结果未知', tone: 'red' },
  old_stopped: { label: '旧卡已停用', tone: 'amber' },
  enabling_new: { label: '启新处理中', tone: 'blue' },
  enable_rejected: { label: '启用被拒·待刷新配置', tone: 'red' },
  active_pending_confirm: { label: '新卡已激活·待客户确认', tone: 'teal' },
  confirmed: { label: '客户已确认可用', tone: 'teal' },
  settled: { label: '已结清办结', tone: 'green' },
  cancelled: { label: '已取消', tone: 'gray' },
  exchange_requested: { label: '受控退换中', tone: 'amber' },
  exchanged: { label: '已受控退换', tone: 'gray' },
}

export const CMD_STATUS_META: Record<string, { label: string; tone: string }> = {
  queued: { label: '排队中', tone: 'gray' },
  sent: { label: '已发·待回执', tone: 'blue' },
  succeeded: { label: '成功', tone: 'green' },
  rejected: { label: '拒绝', tone: 'red' },
  unknown: { label: '结果未知', tone: 'red' },
}

export const KIND_LABEL: Record<string, string> = {
  report_loss: '挂失',
  prepare_profile: '准备配置(2分钟)',
  stop_credential: '停旧凭据(1分钟)',
  enable_credential: '启用新凭据(1分钟)',
  query_command: '查询原指令',
  refresh_profile: '刷新配置',
}

export const REASON_LABEL: Record<string, string> = {
  normal_upgrade: '正常升级换卡（旧卡在手）',
  terminal_change: '更换终端/不兼容',
  damaged: '卡片损坏',
  lost: '客户报失（必须先挂失）',
}

export const STRATEGY_LABEL: Record<string, string> = {
  prepare_first: '先备新后停旧（中断 T+3~T+4）',
  stop_first: '先停旧后备新（中断 T+1~T+4）',
}

export const CARD_STATUS_META: Record<string, { label: string; tone: string }> = {
  in_stock: { label: '在库', tone: 'green' },
  reserved: { label: '已预留', tone: 'blue' },
  in_use: { label: '在用', tone: 'teal' },
  retired: { label: '旧卡已退役', tone: 'gray' },
  released: { label: '已释放', tone: 'gray' },
  quarantine: { label: '隔离/退换', tone: 'red' },
}

export const CRED_STATUS_META: Record<string, { label: string; tone: string }> = {
  active: { label: '当前有效', tone: 'green' },
  preparing: { label: '制作中', tone: 'blue' },
  prepared: { label: '未激活就绪', tone: 'teal' },
  prepare_rejected: { label: '制作被拒', tone: 'red' },
  stopped: { label: '已停用', tone: 'gray' },
  loss_blocked: { label: '挂失停用', tone: 'red' },
  returned: { label: '退换退回', tone: 'gray' },
}

export const TASK_ASSIGNEE_LABEL: Record<string, string> = {
  clerk: '营业员',
  network: '网络办理员',
  customer: '客户',
}

export function fmtDT(s?: string | null): string {
  if (!s) return '—'
  return s.replace('T', ' ').slice(5, 16)
}
export function fmtFull(s?: string | null): string {
  if (!s) return '—'
  return s.replace('T', ' ').slice(0, 16)
}
