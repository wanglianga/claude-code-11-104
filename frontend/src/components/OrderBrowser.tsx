import React, { useEffect, useState } from 'react'
import { get } from '../api'
import { Badge, Empty, usePoll } from '../ui'
import { STATUS_META, STRATEGY_LABEL } from '../labels'
import OrderDetail from './OrderDetail'

export default function OrderBrowser({
  me,
  url = '/orders',
  title,
  hint,
  query,
  top,
  focusId,
}: {
  me: any
  url?: string
  title?: string
  hint?: string
  query?: string
  top?: React.ReactNode
  focusId?: number | null
}) {
  const fullUrl = query ? `${url}?${query}` : url
  const { data } = usePoll<{ items: any[] }>(() => get(fullUrl), [fullUrl], 2200)
  const [selected, setSelected] = useState<number | null>(null)
  const items = data?.items || []

  // 默认选中第一张单；外部 focusId 变化时聚焦新单
  useEffect(() => {
    if (focusId != null) setSelected(focusId)
  }, [focusId])
  useEffect(() => {
    if (selected === null && items.length) setSelected(items[0].id)
  }, [items.length]) // eslint-disable-line

  return (
    <div>
      {top}
      {title && (
        <div className="panel-title" style={{ margin: '2px 2px 12px' }}>
          <h2 style={{ fontSize: 18 }}>{title}</h2>
          {hint && <span className="sub">{hint}</span>}
        </div>
      )}
      <div className="order-layout">
        <div className="panel" style={{ margin: 0, padding: 12, maxHeight: 'calc(100vh - 150px)', overflowY: 'auto' }}>
          {items.length === 0 && <Empty text="暂无订单" />}
          {items.map((o) => (
            <div key={o.id} className={`list-item ${selected === o.id ? 'active' : ''}`}
              onClick={() => setSelected(o.id)}>
              <div className="row1">
                <span className="no">{o.msisdn}</span>
                <Badge meta={STATUS_META} code={o.status} />
              </div>
              <div className="tiny mono">{o.order_no}</div>
              <div className="tiny">{STRATEGY_LABEL[o.strategy]?.split('（')[0]}</div>
            </div>
          ))}
        </div>
        <div>{selected ? <OrderDetail id={selected} me={me} /> : <div className="panel"><Empty text="请选择左侧订单" /></div>}</div>
      </div>
    </div>
  )
}
