import React from 'react'
import { usePoll } from '../ui'
import { CARD_STATUS_META } from '../labels'
import { Badge } from '../ui'
import OrderBrowser from '../components/OrderBrowser'

export default function ClerkPage({ me }: { me: any }) {
  const { data: wb } = usePoll<any>(() => fetch('/api/clerk/workbench', {
    headers: { Authorization: `Bearer ${localStorage.getItem('simswap_token')}` },
  }).then((r) => r.json()), [], 3000)

  const counts = wb?.stock_counts || {}
  const openTasks = (wb?.tasks || []).filter((t: any) => t.status === 'open')

  return (
    <div>
      <div className="grid cols-4" style={{ marginBottom: 16 }}>
        <div className="stat"><div className="v">{counts.in_stock ?? '—'}</div><div className="l">虚构卡库在库</div></div>
        <div className="stat"><div className="v" style={{ color: 'var(--brand)' }}>{counts.reserved ?? 0}</div><div className="l">已预留</div></div>
        <div className="stat"><div className="v" style={{ color: 'var(--teal)' }}>{counts.in_use ?? 0}</div><div className="l">在用卡</div></div>
        <div className="stat"><div className="v" style={{ color: 'var(--amber)' }}>{openTasks.length}</div><div className="l">营业待办</div></div>
      </div>

      <div className="panel">
        <div className="panel-title"><h3>卡库存与兼容性</h3>
          <span className="sub">外形不匹配在分卡时拦截；profile/5G 深层不兼容由网络准备配置时拒绝（如 K0001 + Mate70-X）</span></div>
        <div style={{ maxHeight: 240, overflowY: 'auto' }}>
          <table className="tbl">
            <thead><tr><th>卡面号</th><th>ICCID</th><th>外形</th><th>制式</th><th>Profile</th><th>批次</th><th>状态</th></tr></thead>
            <tbody>
              {(wb?.cards || []).map((c: any) => (
                <tr key={c.id}>
                  <td><b>{c.card_no}</b></td>
                  <td className="mono tiny">{c.iccid}</td>
                  <td>{c.form_factor}</td><td>{c.network_gen}</td><td>{c.profile_type}</td>
                  <td className="tiny">{c.stock_batch}</td>
                  <td><Badge meta={CARD_STATUS_META} code={c.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {openTasks.length > 0 && (
          <div style={{ marginTop: 12 }}>
            {openTasks.slice(0, 6).map((t: any) => (
              <div key={t.id} className="alert amber" style={{ margin: '6px 0' }}>
                <b>{t.title}</b>{t.order_id ? `（订单 #${t.order_id}）` : ''}
                <div className="tiny">{t.detail}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="section-gap" />
      <OrderBrowser me={me} title="营业受理队列"
        hint="核验身份 → 分配兼容实体卡；准备被拒后在此改分卡" />
    </div>
  )
}
