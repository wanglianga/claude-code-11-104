import React, { useMemo, useState } from 'react'
import { get, post } from '../api'
import { runAction, usePoll } from '../ui'
import OrderBrowser from '../components/OrderBrowser'

const REASONS = [
  { v: 'normal_upgrade', l: '正常升级 / 换新型卡，旧卡仍在手中' },
  { v: 'terminal_change', l: '更换新终端，需要兼容配置' },
  { v: 'damaged', l: '卡损坏 / 无信号' },
  { v: 'lost', l: '手机或旧卡遗失（必须先挂失）' },
]

export default function CustomerPage({ me }: { me: any; onGo: (t: string) => void }) {
  const { data: numsData } = usePoll<{ items: any[] }>(() => get('/customer/numbers'), [], 4000)
  const { data: meta } = usePoll<any>(() => get('/meta'), [], 30000)
  const numbers = numsData?.items || []

  const [msisdn, setMsisdn] = useState('')
  const [reason, setReason] = useState('normal_upgrade')
  const [oldInHand, setOldInHand] = useState(true)
  const [strategy, setStrategy] = useState('prepare_first')
  const [terminalModel, setTerminalModel] = useState('Mate70-X')
  const [loseStopFault, setLoseStopFault] = useState(false)
  const [focusId, setFocusId] = useState<number | null>(null)

  const effectiveMsisdn = msisdn || numbers[0]?.msisdn || ''
  const lost = reason === 'lost'
  const finalStrategy = lost ? 'stop_first' : strategy
  const selectedNumber = useMemo(
    () => numbers.find((n) => n.msisdn === effectiveMsisdn),
    [numbers, effectiveMsisdn],
  )

  async function submit() {
    const fault_flags: any = {}
    if (loseStopFault) fault_flags.stop_fault = 'lose_response'
    const body = {
      msisdn: effectiveMsisdn, reason,
      old_card_in_hand: lost ? false : oldInHand,
      strategy: finalStrategy,
      terminal_model: terminalModel || null,
      fault_flags,
    }
    try {
      const o = await runAction(post('/orders', body), '申请已提交：请完成身份核验')
      setFocusId(o.id)
    } catch { /* toast 已处理 */ }
  }

  return (
    <div>
      <div className="panel">
        <div className="panel-title">
          <h2 style={{ fontSize: 18 }}>客户申请：提出换卡原因并选择办理时序</h2>
          <span className="sub">系统会先给出预计通信中断时刻；提交后在下方订单中完成核验、确认与结清</span>
        </div>

        {numbers.length > 0 && (
          <div className="grid cols-3" style={{ marginBottom: 16 }}>
            {numbers.slice(0, 3).map((n) => (
              <div key={n.id} className="stat" style={{ cursor: 'pointer', outline: n.msisdn === effectiveMsisdn ? '2px solid var(--brand)' : undefined }}
                onClick={() => setMsisdn(n.msisdn)}>
                <div className="l">我的号码</div>
                <div className="v" style={{ fontSize: 19 }}>{n.msisdn}</div>
                <div className="tiny">{n.plan?.name} · 账期日每月 {n.billing_cycle_day} 日</div>
                <div className="tiny">本账期已用流量 {n.cycle_data_used_mb}MB / 通话 {n.cycle_voice_used_min} 分 / 权益 {n.benefits_used_count} 次（换卡不清零）</div>
              </div>
            ))}
          </div>
        )}

        <div className="form-row">
          <label className="field"><span>办理号码</span>
            <select value={effectiveMsisdn} onChange={(e) => setMsisdn(e.target.value)}>
              {numbers.map((n) => <option key={n.id} value={n.msisdn}>{n.msisdn}（{n.plan?.name}）</option>)}
            </select>
          </label>
          <label className="field"><span>换卡原因</span>
            <select value={reason} onChange={(e) => {
              setReason(e.target.value)
              if (e.target.value === 'lost') setStrategy('stop_first')
            }}>
              {REASONS.map((r) => <option key={r.v} value={r.v}>{r.l}</option>)}
            </select>
          </label>
        </div>

        <div className="form-row">
          <label className="field"><span>新终端（用于兼容性校验，可空）</span>
            <select value={terminalModel} onChange={(e) => setTerminalModel(e.target.value)}>
              <option value="">不指定</option>
              {meta?.terminals?.map((t: any) => <option key={t.id} value={t.model}>{t.brand} {t.model}</option>)}
            </select>
          </label>
          <label className="field"><span>旧卡是否仍在本人手中</span>
            <select value={oldInHand ? 'yes' : 'no'} disabled={lost}
              onChange={(e) => { setOldInHand(e.target.value === 'yes'); if (e.target.value !== 'yes') setStrategy('stop_first') }}>
              <option value="yes">在手中、可立即交换</option>
              <option value="no">不在手中 / 无法使用旧卡</option>
            </select>
          </label>
        </div>

        <label className="field"><span>办理时序（两条路径均满足“一个号码最多一个有效激活凭据”）</span>
          <div className="grid cols-2">
            <button type="button" className="list-item" disabled={lost || !oldInHand}
              style={{ outline: finalStrategy === 'prepare_first' ? '2px solid var(--brand)' : undefined, opacity: lost || !oldInHand ? .5 : 1 }}
              onClick={() => setStrategy('prepare_first')}>
              <b>先准备未激活新配置，再停旧</b>
              <div className="tiny">总 4 分钟：备配置 2 + 停旧 1 + 启新 1；预计仅 <b style={{ color: 'var(--red)' }}>T+3~T+4</b> 中断。旧凭据多存续约 2 分钟；准备失败时旧卡不受影响。</div>
            </button>
            <button type="button" className="list-item"
              style={{ outline: finalStrategy === 'stop_first' ? '2px solid var(--brand)' : undefined }}
              onClick={() => setStrategy('stop_first')}>
              <b>先停旧，再准备并启用新配置</b>
              <div className="tiny">总 4 分钟：停旧 1 + 备配置 2 + 启新 1；预计 <b style={{ color: 'var(--red)' }}>T+1~T+4</b> 中断。撤旧凭据更早，但客户等待更久；准备失败会延长无服务时间。</div>
            </button>
          </div>
        </label>

        {lost && <div className="alert red">报失号码必须<b>先挂失</b>，不能使用“先准备新配置”的正常升级策略继续保留遗失卡。系统已强制为先停旧路径。</div>}

        <label className="field" style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <input type="checkbox" style={{ width: 'auto' }} checked={loseStopFault}
            onChange={(e) => setLoseStopFault(e.target.checked)} />
          <span style={{ margin: 0 }}>演练注入：停旧指令“网络成功但响应丢失”（用于验证 unknown → 查询原指令流程）</span>
        </label>

        <button className="btn primary" style={{ padding: '10px 22px' }} onClick={submit}>
          提交换卡申请
        </button>
        {selectedNumber && (
          <span className="tiny" style={{ marginLeft: 12 }}>
            当前有效凭据：{selectedNumber.active_credential?.credential_code || '无'}
          </span>
        )}
      </div>

      <div className="section-gap" />
      <OrderBrowser me={me} title="我的换卡单与办理追踪"
        hint="展开每张单可看预计/实际时刻、指令四态、回执、待办、联系人"
        focusId={focusId} />
    </div>
  )
}
