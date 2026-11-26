import React, { useState } from 'react'
import { get, post } from '../api'
import { Badge, runAction, usePoll } from '../ui'
import { CMD_STATUS_META, KIND_LABEL } from '../labels'
import OrderBrowser from '../components/OrderBrowser'

export default function NetworkPage({ me }: { me: any }) {
  const { data: wb } = usePoll<any>(() => get('/network/workbench'), [], 2000)
  const [focusId, setFocusId] = useState<number | null>(null)

  const tasks = (wb?.tasks || []).filter((t: any) => t.status === 'open')
  const unknownCmds = (wb?.commands || []).filter((c: any) => c.status === 'unknown')
  const sentCmds = (wb?.commands || []).filter((c: any) => c.status === 'sent')

  async function tick(n: number) {
    await runAction(post('/sim/tick', { minutes: n }), `模拟时间推进 ${n} 分钟`)
  }
  async function queryCmd(id: number) {
    await runAction(post(`/commands/${id}/query`), '查询原指令已下发，推进 1 分钟可见回执')
  }

  return (
    <div>
      <div className="grid cols-4" style={{ marginBottom: 16 }}>
        <div className="stat"><div className="v" style={{ color: 'var(--amber)' }}>{tasks.length}</div><div className="l">网络待办</div></div>
        <div className="stat"><div className="v" style={{ color: 'var(--red)' }}>{unknownCmds.length}</div><div className="l">结果未知指令</div></div>
        <div className="stat"><div className="v" style={{ color: 'var(--brand)' }}>{sentCmds.length}</div><div className="l">已发待回执</div></div>
        <div className="stat">
          <div className="v" style={{ fontSize: 16, paddingTop: 4 }}>
            <button className="btn sm" onClick={() => tick(1)}>+1 模拟分</button>{' '}
            <button className="btn sm primary" onClick={() => tick(2)}>+2 分</button>{' '}
            <button className="btn sm" onClick={() => tick(4)}>+4 分</button>
          </div>
          <div className="l">推进模拟时钟（2/1/1 分钟）</div>
        </div>
      </div>

      {(unknownCmds.length > 0 || tasks.some((t: any) => t.type === 'query_stop')) && (
        <div className="alert red">
          <b>纪律：</b>停旧结果未知时，只能“查询原指令”，<b>不能按超时当失败去开第二张卡</b>，也不能启用新卡。
        </div>
      )}

      <div className="panel">
        <div className="panel-title"><h3>网络任务清单</h3><span className="sub">点击任务可定位到对应订单</span></div>
        {tasks.length === 0 && <div className="tiny">暂无网络台待办</div>}
        {tasks.slice(0, 10).map((t: any) => (
          <div key={t.id} className="list-item" style={{ marginBottom: 7 }}
            onClick={() => t.order_id && setFocusId(t.order_id)}>
            <div className="row1">
              <span className="badge amber">待办</span>
              <b style={{ fontSize: 13.5 }}>{t.title}</b>
              {t.order_id && <span className="tiny" style={{ marginLeft: 'auto' }}>订单 #{t.order_id}</span>}
            </div>
            <div className="tiny">{t.detail}</div>
          </div>
        ))}
      </div>

      <div className="panel">
        <div className="panel-title"><h3>最近网络指令</h3>
          <span className="sub">已发 / 成功 / 拒绝 / 未知 四态与预计、实际时刻</span></div>
        <div style={{ maxHeight: 260, overflowY: 'auto' }}>
          <table className="tbl">
            <thead><tr><th>指令号</th><th>类型</th><th>状态</th><th>预计完成</th><th>响应</th><th></th></tr></thead>
            <tbody>
              {(wb?.commands || []).slice(0, 30).map((c: any) => (
                <tr key={c.id} className="clickable" onClick={() => c.order_id && setFocusId(c.order_id)}>
                  <td className="mono tiny">{c.command_no}</td>
                  <td>{KIND_LABEL[c.kind] || c.kind}</td>
                  <td><Badge meta={CMD_STATUS_META} code={c.status} /></td>
                  <td className="tiny num">{(c.estimated_complete_at_sim || '').replace('T', ' ').slice(5, 16)}</td>
                  <td className="tiny">{c.response_code} {c.response_message ? '· ' + c.response_message.slice(0, 40) : ''}</td>
                  <td onClick={(e) => e.stopPropagation()}>
                    {c.status === 'unknown' && c.kind !== 'query_command' && me?.role !== 'customer' && (
                      <button className="btn sm red" onClick={() => queryCmd(c.id)}>查询原指令</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="section-gap" />
      <OrderBrowser me={me} title="全部办理单 · 网络推进"
        hint="在订单详情中按状态下发 挂失/准备/停旧/启新/查询/刷新 指令，并用顶部模拟钟推进回执"
        focusId={focusId} />
    </div>
  )
}
