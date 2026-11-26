import React, { useEffect, useRef, useState } from 'react'
import { ApiError } from './api'

export function toast(message: string, kind: 'ok' | 'err' = 'ok') {
  window.dispatchEvent(new CustomEvent('app-toast', { detail: { message, kind } }))
}

export function Toaster() {
  const [items, setItems] = useState<{ id: number; message: string; kind: string }[]>([])
  useEffect(() => {
    let id = 0
    const h = (e: any) => {
      const myId = ++id
      setItems((x) => [...x, { id: myId, ...e.detail }])
      setTimeout(() => setItems((x) => x.filter((i) => i.id !== myId)), 4200)
    }
    window.addEventListener('app-toast', h)
    return () => window.removeEventListener('app-toast', h)
  }, [])
  return (
    <div className="toast-wrap">
      {items.map((i) => (
        <div key={i.id} className={`toast ${i.kind === 'err' ? 'err' : 'ok'}`}>
          {i.message}
        </div>
      ))}
    </div>
  )
}

export function Badge({ meta, code }: { meta: Record<string, { label: string; tone: string }>; code: string }) {
  const m = meta[code] || { label: code, tone: 'gray' }
  return (
    <span className={`badge ${m.tone}`}>
      <span className="dot" />
      {m.label}
    </span>
  )
}

/** 轮询 + 监听 data-changed / sim-tick 立即刷新 */
export function usePoll<T>(fn: () => Promise<T>, deps: any[] = [], intervalMs = 2500) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const fnRef = useRef(fn)
  fnRef.current = fn
  const reload = async () => {
    try {
      const d = await fnRef.current()
      setData(d)
      setError(null)
    } catch (e: any) {
      setError(e?.message || '加载失败')
    }
  }
  useEffect(() => {
    reload()
    const t = setInterval(reload, intervalMs)
    const onChange = () => reload()
    window.addEventListener('data-changed', onChange)
    return () => {
      clearInterval(t)
      window.removeEventListener('data-changed', onChange)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return { data, error, reload }
}

/** 执行一个动作并统一报错/提示/刷新 */
export async function runAction(p: Promise<any>, okMsg?: string): Promise<any> {
  try {
    const r = await p
    if (okMsg) toast(okMsg, 'ok')
    window.dispatchEvent(new Event('data-changed'))
    return r
  } catch (e) {
    const msg = e instanceof ApiError ? `${e.code}：${e.message}` : String(e)
    toast(msg, 'err')
    throw e
  }
}

export function Spinner() {
  return <span className="spinner" />
}

export function Empty({ text = '暂无数据' }: { text?: string }) {
  return <div className="empty">{text}</div>
}

export function useNowTick(refreshMs = 1000) {
  const [, setN] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setN((x) => x + 1), refreshMs)
    return () => clearInterval(t)
  }, [refreshMs])
}
