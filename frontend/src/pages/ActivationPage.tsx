import React from 'react'
import { get } from '../api'
import { usePoll } from '../ui'
import { CRED_STATUS_META } from '../labels'
import { Badge } from '../ui'
import OrderBrowser from '../components/OrderBrowser'

export default function ActivationPage({ me }: { me: any }) {
  const { data: wb } = usePoll<any>(() => get('/activation/workbench'), [], 2500)
  const creds = wb?.credentials || []
  const active = creds.filter((c: any) => c.status === 'active').length
  const stale = creds.filter((c: any) => c.profile_stale).length

  return (
    <div>
      <div className="hero-note">
        激活核验台：制卡完成只代表“未激活配置就绪(prepared)”；一个号码同一时刻最多一个 active 凭据（PostgreSQL 部分唯一索引兜底）。
        网络启用成功后，还必须由客户运行信号/数据/通话/短信探测并亲自确认“新卡实际可用”，随后才能结清。
      </div>
      <div className="grid cols-4" style={{ marginBottom: 16 }}>
        <div className="stat"><div className="v" style={{ color: 'var(--green)' }}>{active}</div><div className="l">全局有效激活凭据（每号至多 1）</div></div>
        <div className="stat"><div className="v" style={{ color: 'var(--teal)' }}>{creds.filter((c: any) => c.status === 'prepared').length}</div><div className="l">未激活就绪配置</div></div>
        <div className="stat"><div className="v" style={{ color: 'var(--red)' }}>{stale}</div><div className="l">套餐版本过期待刷新</div></div>
        <div className="stat"><div className="v">{creds.length}</div><div className="l">凭据身份总数（独立于卡/号码）</div></div>
      </div>

      <div className="panel">
        <div className="panel-title"><h3>激活凭据台账</h3><span className="sub">注意同一号码不会出现两个 active</span></div>
        <div style={{ maxHeight: 280, overflowY: 'auto' }}>
          <table className="tbl">
            <thead><tr><th>凭据号</th><th>号码ID</th><th>订单</th><th>状态</th><th>配置套餐版本</th><th>过期</th><th>激活时刻</th></tr></thead>
            <tbody>
              {creds.slice(0, 40).map((c: any) => (
                <tr key={c.id}>
                  <td className="mono tiny">{c.credential_code}</td>
                  <td>{c.number_id}</td>
                  <td>{c.order_id || '—'}</td>
                  <td><Badge meta={CRED_STATUS_META} code={c.status} /></td>
                  <td>v{c.profile_plan_version} · {c.profile_snapshot?.plan_code}</td>
                  <td>{c.profile_stale ? <span className="badge red">stale</span> : '—'}</td>
                  <td className="tiny num">{(c.activated_at_sim || '').replace('T', ' ').slice(5, 16)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="section-gap" />
      <OrderBrowser me={me} title="激活核验与客户确认"
        hint="对 active_pending_confirm 订单先运行探测，再由客户确认，最后结清；已启新取消只能受控退换"
        query="status=active_pending_confirm" />
      <div className="section-gap" />
      <OrderBrowser me={me} title="已确认 / 已结清 / 退换订单"
        query="status=confirmed,settled,exchanged" />
    </div>
  )
}
