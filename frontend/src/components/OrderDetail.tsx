import React, { useState } from 'react'
import { get, post } from '../api'
import {
  Badge, Empty, runAction, usePoll,
} from '../ui'
import {
  CARD_STATUS_META, CRED_STATUS_META, CMD_STATUS_META, KIND_LABEL,
  REASON_LABEL, STATUS_META, STRATEGY_LABEL, TASK_ASSIGNEE_LABEL,
  fmtDT, fmtFull,
} from '../labels'

function parseDT(s?: string | null): Date | null {
  if (!s) return null
  return new Date(s.replace(' ', 'T'))
}

/** 相对 T0 的模拟分钟偏移 */
function offMin(s: string | null | undefined, t0?: string | null): number | null {
  const a = parseDT(s)
  const b = parseDT(t0)
  if (!a || !b) return null
  return Math.round((a.getTime() - b.getTime()) / 60000)
}

function MinuteRuler({ o }: { o: any }) {
  const pS = offMin(o.outage_start_planned_sim, o.t0_sim)
  const pE = offMin(o.outage_end_planned_sim, o.t0_sim)
  const aS = offMin(o.outage_start_actual_sim, o.t0_sim)
  const aE = offMin(o.outage_end_actual_sim, o.t0_sim)
  const kindCell: Record<number, string> = {}
  const labelCell: Record<number, string> = {}
  for (const st of o.planned?.steps || []) {
    for (let m = st.start_min; m < st.end_min; m++) {
      kindCell[m] = st.key === 'prepare' ? 'prep' : st.key === 'stop' ? 'stop' : 'enable'
      labelCell[m] = st.key === 'prepare' ? '备配置' : st.key === 'stop' ? '停旧' : '启新'
    }
  }
  const n = Math.max(4, Math.ceil(aE ?? 0) + 1, Math.ceil(pE ?? 4))
  const cells = Array.from({ length: n }, (_, m) => m)
  return (
    <div>
      <div className="tiny">办理分钟轴（T0 = {fmtFull(o.t0_sim)}）</div>
      <div className="minute-bar" style={{ gridTemplateColumns: `repeat(${n},1fr)` }}>
        {cells.map((m) => {
          const plannedOutage = pS !== null && pE !== null && m >= pS && m < pE
          const actualOutage = aS !== null && aE !== null && m >= aS && m < aE
          return (
            <div key={m}
              className={`min-cell ${kindCell[m] || ''} ${plannedOutage ? 'outage' : ''} ${actualOutage ? 'actual-out' : ''}`}
              title={`T+${m} ~ T+${m + 1}`}>
              T+{m}
              <div style={{ fontWeight: 500, fontSize: 10.5 }}>{labelCell[m] || ' '}</div>
            </div>
          )
        })}
      </div>
      <div className="outage-legend">
        <span><i className="legend-i" style={{ background: '#dce8ff' }} />准备配置(2分)</span>
        <span><i className="legend-i" style={{ background: '#fde2c4' }} />停旧(1分)</span>
        <span><i className="legend-i" style={{ background: '#d8f3e3' }} />启新(1分)</span>
        <span><i className="legend-i" style={{ background: 'transparent', outline: '2px solid var(--red)' }} />预计中断区间</span>
        <span><i className="legend-i" style={{ background: '#f8c9c9' }} />实际中断区间</span>
      </div>
      <div className="grid cols-2 section-gap">
        <div className="alert blue" style={{ margin: 0 }}>
          预计通信中断：{o.planned?.outage_label || '—'}<br />
          <span className="tiny">{fmtFull(o.outage_start_planned_sim)} ~ {fmtFull(o.outage_end_planned_sim)}</span>
        </div>
        <div className={aS !== null ? 'alert red' : 'alert amber'} style={{ margin: 0 }}>
          实际通信中断：{aS !== null ? `T+${aS} ~ T+${aE ?? '…'} 分钟` : '尚未开始（旧凭据仍有效）'}
          {aS !== null && <><br /><span className="tiny">{fmtFull(o.outage_start_actual_sim)} ~ {fmtFull(o.outage_end_actual_sim)}</span></>}
        </div>
      </div>
    </div>
  )
}

function ActionButton({ me, roles, ...props }: any) {
  const allowed = me?.role === 'admin' || roles.includes(me?.role)
  if (!allowed) return null
  return <button {...props} />
}

export default function OrderDetail({ id, me }: { id: number; me: any }) {
  const { data: o, reload } = usePoll<any>(() => get(`/orders/${id}`), [id], 1800)
  const { data: cardsData } = usePoll<any>(() => get('/cards?status=in_stock'), [id], 4000)
  const [idNo, setIdNo] = useState('')
  const [cardNo, setCardNo] = useState('')
  if (!o) return <div className="panel"><Empty text="加载订单中…" /></div>

  const can = (...roles: string[]) => me?.role === 'admin' || roles.includes(me?.role)
  const latestIdentity = o.identities?.[o.identities.length - 1]
  const unknownStop = o.commands?.find((c: any) => c.kind === 'stop_credential' && c.status === 'unknown')
  const terminalStatus = ['settled', 'cancelled', 'exchanged'].includes(o.status)
  const inStockCards: any[] = cardsData?.items || []

  const act = (p: Promise<any>, msg?: string) => runAction(p, msg).then(() => reload()).catch(() => {})

  return (
    <div>
      <div className="panel">
        <div className="panel-title">
          <h3 className="mono">{o.order_no}</h3>
          <Badge meta={STATUS_META} code={o.status} />
          <span className="tiny">{o.number?.msisdn} · {REASON_LABEL[o.reason]}</span>
          <div className="right">
            {!terminalStatus && can('customer', 'clerk') && !['active_pending_confirm', 'confirmed', 'settled', 'exchange_requested'].includes(o.status) && (
              <button className="btn sm red"
                onClick={() => confirm('确认取消该订单？未启新前可直接取消并释放卡预留。') &&
                  act(post(`/orders/${o.id}/cancel`), '订单已取消')}>
                取消订单
              </button>
            )}
            {can('customer', 'clerk') && ['active_pending_confirm', 'confirmed', 'settled'].includes(o.status) && (
              <button className="btn sm amber"
                onClick={() => {
                  const reason = prompt('受控退换原因：', '客户在新卡激活后申请取消')
                  if (reason !== null) act(post(`/orders/${o.id}/exchange`, { reason }), '已发起受控退换')
                }}>
                已启新·受控退换
              </button>
            )}
          </div>
        </div>

        <div className="hero-note">
          时序：{STRATEGY_LABEL[o.strategy]}；{o.old_card_in_hand ? '旧卡仍在客户手中' : '旧卡不在手中/遗失'}。
          失败联系人：{o.failure_contact}
        </div>

        <MinuteRuler o={o} />
      </div>

      {/* 待办与操作 */}
      <div className="panel">
        <div className="panel-title"><h3>当前办理动作</h3>
          <span className="sub">后端按状态机严格守卫，越序操作会返回 409/422</span></div>
        <div className="right-actions">
          {['submitted', 'identity_failed'].includes(o.status) && can('customer', 'clerk') && (
            <>
              <input style={{ width: 220 }} placeholder="开户证件号"
                value={idNo || o.customer_brief?.id_number || ''}
                onChange={(e) => setIdNo(e.target.value)} />
              <button className="btn primary"
                onClick={() => act(post(`/orders/${o.id}/verify-identity`,
                  { id_number: idNo || o.customer_brief?.id_number }), '身份核验已完成')}>
                提交身份核验
              </button>
              <span className="tiny">提示：演练证件号 {o.customer_brief?.id_number}</span>
            </>
          )}
          {o.status === 'pending_assignment' && can('clerk') && (
            <>
              <select value={cardNo} onChange={(e) => setCardNo(e.target.value)} style={{ width: 260 }}>
                <option value="">选择在库卡（先核外形兼容）…</option>
                {inStockCards.map((c) => (
                  <option key={c.id} value={c.card_no}>
                    {c.card_no} · {c.form_factor}/{c.network_gen}/{c.profile_type}
                  </option>
                ))}
              </select>
              <button className="btn" disabled={!cardNo}
                onClick={() => act(post(`/orders/${o.id}/assign-card`, { card_no: cardNo }), '已分配卡')}>
                分配所选卡
              </button>
              <button className="btn primary"
                onClick={() => act(post(`/orders/${o.id}/assign-card`, { auto: true }), '已自动分配通用兼容卡')}>
                自动分配兼容卡
              </button>
            </>
          )}
          {o.status === 'prepare_failed' && can('clerk') && (
            <>
              <select value={cardNo} onChange={(e) => setCardNo(e.target.value)} style={{ width: 260 }}>
                <option value="">改分另一张在库卡…</option>
                {inStockCards.map((c) => (
                  <option key={c.id} value={c.card_no}>
                    {c.card_no} · {c.form_factor}/{c.network_gen}/{c.profile_type}
                  </option>
                ))}
              </select>
              <button className="btn red" disabled={!cardNo}
                onClick={() => act(post(`/orders/${o.id}/assign-card`, { card_no: cardNo }), '已改分卡')}>
                重新分配兼容卡
              </button>
            </>
          )}

          {o.reason === 'lost' && !o.commands?.some((c: any) => c.kind === 'report_loss' && c.status === 'succeeded')
            && can('network') && (
              <button className="btn amber" onClick={() => act(post(`/orders/${o.id}/report-loss`), '挂失已成功')}>
                ① 下发挂失指令（即时）
              </button>
            )}
          {o.status === 'card_assigned' && o.strategy === 'prepare_first' && can('network') && (
            <button className="btn primary" onClick={() => act(post(`/orders/${o.id}/prepare`), '准备配置指令已发（2 模拟分钟）')}>
              下发准备配置（2 分钟）
            </button>
          )}
          {o.status === 'card_assigned' && o.strategy === 'stop_first' && can('network') && (
            <button className="btn amber" onClick={() => act(post(`/orders/${o.id}/stop`), '停旧指令已发（1 分钟）')}>
              下发停旧指令（1 分钟）
            </button>
          )}
          {o.status === 'loss_reported' && can('network') && (
            <button className="btn amber" onClick={() => act(post(`/orders/${o.id}/stop`), '停旧指令已发（1 分钟）')}>
              挂失后下发停旧（1 分钟）
            </button>
          )}
          {o.status === 'prepared' && can('network') && (
            <button className="btn amber" onClick={() => act(post(`/orders/${o.id}/stop`), '停旧指令已发（1 分钟）')}>
              下发停旧指令（1 分钟）
            </button>
          )}
          {o.status === 'old_stopped' && can('network') && (
            <>
              {o.strategy === 'stop_first' && !o.commands?.some((c: any) => c.kind === 'prepare_profile' && c.status === 'succeeded') && (
                <button className="btn primary" onClick={() => act(post(`/orders/${o.id}/prepare`), '准备配置指令已发（2 分钟）')}>
                  旧已停·准备新配置（2 分钟）
                </button>
              )}
              <button className="btn green" onClick={() => act(post(`/orders/${o.id}/enable`), '启用指令已发（1 分钟）')}>
                下发启用新配置（1 分钟）
              </button>
            </>
          )}
          {o.status === 'enable_rejected' && can('network') && (
            <button className="btn primary" onClick={() => act(post(`/orders/${o.id}/refresh`), '刷新配置指令已发（1 分钟）')}>
              刷新配置到最新套餐版本
            </button>
          )}
          {unknownStop && can('network') && (
            <button className="btn red"
              onClick={() => act(post(`/commands/${unknownStop.id}/query`), '查询原指令已发（1 分钟）')}>
              结果未知·查询原指令 {unknownStop.command_no}
            </button>
          )}
          {o.status === 'active_pending_confirm' && can('customer', 'network') && (
            <button className="btn primary" onClick={() => act(post(`/orders/${o.id}/probes`), '探测完成：信号/数据/通话/短信均正常')}>
              运行激活可用性探测
            </button>
          )}
          {o.status === 'active_pending_confirm' && can('customer') && (
            <button className="btn green" disabled={!o.activation_checks?.ready}
              title={o.activation_checks?.ready ? '' : '请先运行探测'}
              onClick={() => act(post(`/orders/${o.id}/confirm`), '客户已确认新卡实际可用')}>
              我确认新卡可用
            </button>
          )}
          {o.status === 'confirmed' && can('customer', 'clerk') && (
            <button className="btn green"
              onClick={() => act(post(`/orders/${o.id}/settle`, { channel: '虚构支付-话费账户' }), '已结清，流程办结')}>
              结清 ¥{o.settlement?.amount ?? 10}
            </button>
          )}
          {o.exchange?.status === 'requested' && can('network') && (
            <button className="btn red"
              onClick={() => act(post(`/exchange/${o.exchange.id}/complete`), '受控退换已办结')}>
              网络台完成停退新凭据
            </button>
          )}
        </div>

        {latestIdentity && latestIdentity.result !== 'pending' && (
          <div className={`alert ${latestIdentity.result === 'pass' ? 'green' : 'red'}`}>
            身份核验：{latestIdentity.result === 'pass' ? '通过' : '未通过'}（评分 {latestIdentity.score}）
            <span className="tiny"> · {latestIdentity.channel} · {fmtFull(latestIdentity.verified_at_sim)}</span>
          </div>
        )}
        {o.status === 'stop_old_unknown' && (
          <div className="alert red">
            停旧指令结果未知：只能先查询原指令核对网络真实结果，<b>不能按超时当失败去开第二张卡</b>，也不能启用新卡。
          </div>
        )}
        {o.activation_checks?.ready && (
          <div className="alert green">
            激活核验通过（{fmtDT(o.activation_checks.probed_at_sim)}）：
            {Object.values(o.activation_checks).filter((x: any) => x?.item).map((x: any) => x.item).join('、')}
          </div>
        )}
      </div>

      <div className="grid cols-2 section-gap" style={{ alignItems: 'start' }}>
        {/* 实体卡 + 凭据配置 */}
        <div className="panel" style={{ margin: 0 }}>
          <div className="panel-title"><h3>实体卡与激活凭据</h3></div>
          <dl className="kv">
            <dt>分配实体卡</dt>
            <dd>{o.card ? <>{o.card.card_no} / {o.card.iccid}
              <Badge meta={CARD_STATUS_META} code={o.card.status} />
              <div className="tiny">{o.card.form_factor} · {o.card.network_gen} · {o.card.profile_type}</div></> : '尚未分配'}</dd>
            <dt>旧凭据</dt>
            <dd>{o.old_credential ? <><span className="mono">{o.old_credential.credential_code}</span>{' '}
              <Badge meta={CRED_STATUS_META} code={o.old_credential.status} /></> : '—'}</dd>
            <dt>新凭据</dt>
            <dd>{o.new_credential ? <><span className="mono">{o.new_credential.credential_code}</span>{' '}
              <Badge meta={CRED_STATUS_META} code={o.new_credential.status} />
              {o.new_credential.profile_stale && <span className="badge red" style={{ marginLeft: 6 }}>配置套餐过期</span>}
            </> : '尚未制作'}</dd>
          </dl>
          {o.new_credential && (
            <>
              <div className="tiny" style={{ margin: '10px 0 4px' }}>新配置内容快照（继承已确认套餐/权限，不重置权益）</div>
              <pre className="profile-box">{JSON.stringify(o.new_credential.profile_snapshot, null, 2)}</pre>
            </>
          )}
        </div>

        {/* 待办 + 结算/退换 */}
        <div className="panel" style={{ margin: 0 }}>
          <div className="panel-title"><h3>仍需办理的任务</h3></div>
          {o.tasks?.length ? o.tasks.map((t: any) => (
            <div key={t.id} style={{ padding: '8px 0', borderBottom: '1px dashed var(--line)', opacity: t.status === 'open' ? 1 : .62 }}>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <span className={`badge ${t.status === 'open' ? 'amber' : t.status === 'cancelled' ? 'gray' : 'green'}`}>
                  {t.status === 'open' ? '待办' : t.status === 'cancelled' ? '已作废' : '已完成'}
                </span>
                <b style={{ fontSize: 13 }}>{t.title}</b>
                <span className="tiny" style={{ marginLeft: 'auto' }}>{TASK_ASSIGNEE_LABEL[t.assignee_role]}</span>
              </div>
              <div className="tiny" style={{ marginTop: 3 }}>{t.detail}</div>
            </div>
          )) : <Empty text="暂无任务" />}

          {o.settlement && (
            <div className="alert blue" style={{ marginTop: 12 }}>
              结算单：¥{o.settlement.amount} ·
              <Badge meta={{ pending: { label: '待支付', tone: 'amber' }, paid: { label: '已支付', tone: 'green' } }}
                code={o.settlement.status} />
              <div className="tiny">{(o.settlement.items || []).map((i: any) => i.name).join('；')} · 支付时刻 {fmtDT(o.settlement.paid_at_sim)}</div>
            </div>
          )}
          {o.exchange && (
            <div className="alert amber" style={{ marginTop: 12 }}>
              受控退换 {o.exchange.case_no}：状态 {o.exchange.status}。{o.exchange.note}
            </div>
          )}
        </div>
      </div>

      {/* 指令四态 */}
      <div className="panel">
        <div className="panel-title"><h3>网络指令（已发 / 成功 / 拒绝 / 结果未知）</h3>
          <span className="sub">预计完成时刻 vs 实际确认时刻分别展示</span></div>
        <div style={{ overflowX: 'auto' }}>
          <table className="tbl">
            <thead><tr>
              <th>指令号</th><th>类型</th><th>状态</th><th>下发时刻</th><th>预计完成</th>
              <th>实际/网络执行</th><th>响应码与信息</th><th></th>
            </tr></thead>
            <tbody>
              {o.commands?.map((c: any) => (
                <tr key={c.id}>
                  <td className="mono">{c.command_no}</td>
                  <td>{KIND_LABEL[c.kind] || c.kind}
                    {c.fault_mode !== 'normal' && <div className="tiny" style={{ color: 'var(--red)' }}>故障：{c.fault_mode}</div>}
                  </td>
                  <td><Badge meta={CMD_STATUS_META} code={c.status} /></td>
                  <td className="num tiny">{fmtDT(c.sent_at_sim)}</td>
                  <td className="num tiny">{fmtDT(c.estimated_complete_at_sim)}</td>
                  <td className="num tiny">{fmtDT(c.completed_at_sim || c.adapter_executed_at_sim)}</td>
                  <td style={{ maxWidth: 280 }}>
                    <b>{c.response_code || ''}</b>
                    <div className="tiny">{c.response_message}</div>
                  </td>
                  <td>
                    {c.status === 'unknown' && can('network') && c.kind !== 'query_command' && (
                      <button className="btn sm red"
                        onClick={() => act(post(`/commands/${c.id}/query`), '查询原指令已发')}>
                        查询原指令
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 回执流水 */}
      <div className="panel">
        <div className="panel-title"><h3>回执流水（含迟到 / 重复回执留痕）</h3></div>
        {o.receipts?.length ? (
          <table className="tbl">
            <thead><tr><th>回执号</th><th>对应指令</th><th>结果</th><th>接收时刻</th><th>是否入账</th><th>说明</th></tr></thead>
            <tbody>
              {o.receipts.map((r: any) => (
                <tr key={r.id}>
                  <td className="mono tiny">{r.receipt_no}</td>
                  <td className="mono tiny">{r.command_no}
                    {r.original_command_no && r.original_command_no !== r.command_no &&
                      <div className="tiny">via {r.original_command_no}</div>}
                  </td>
                  <td><Badge meta={{ succeeded: { label: '成功', tone: 'green' }, rejected: { label: '拒绝', tone: 'red' } }} code={r.outcome} /></td>
                  <td className="num tiny">{fmtDT(r.received_at_sim)}</td>
                  <td>{r.applied ? <span className="badge green">已应用</span>
                    : <span className="badge gray">已忽略</span>}</td>
                  <td className="tiny">{r.ignore_reason || r.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <Empty text="暂无回执" />}
      </div>

      {/* 场景注入（演练用） */}
      {can('clerk', 'network') && (
        <div className="panel">
          <div className="panel-title"><h3>演练场景注入</h3><span className="sub">用于复现“准备中套餐变更 / 旧启用回执晚到”</span></div>
          <div className="right-actions">
            <button className="btn"
              onClick={() => act(post('/scenarios/plan-change',
                { msisdn: o.number.msisdn, to_plan_code: 'PLAN_5G_299', approve: true }),
                '套餐变更已批准，plan_version+1')}>
              批准套餐变更为 299 元档（准备中点）
            </button>
            <button className="btn"
              onClick={() => act(post('/scenarios/late-receipt',
                { msisdn: o.number.msisdn, delay_min: 3, duplicate: true }),
                '已编排 3 分钟后投递旧启用迟到回执')}>
              编排旧启用回执 3 分钟后晚到
            </button>
          </div>
          {o.fault_flags && Object.keys(o.fault_flags).length > 0 && (
            <div className="tiny" style={{ marginTop: 8 }}>本单故障注入：{JSON.stringify(o.fault_flags)}</div>
          )}
        </div>
      )}
    </div>
  )
}
