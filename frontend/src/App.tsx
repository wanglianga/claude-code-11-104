import React, { useEffect, useState } from 'react'
import { get, post, setToken, getToken } from './api'
import { Toaster, runAction } from './ui'
import Login from './pages/Login'
import CustomerPage from './pages/CustomerPage'
import ClerkPage from './pages/ClerkPage'
import NetworkPage from './pages/NetworkPage'
import ActivationPage from './pages/ActivationPage'

const TABS = [
  { key: 'customer', label: '① 客户申请' },
  { key: 'clerk', label: '② 营业办理' },
  { key: 'network', label: '③ 网络任务' },
  { key: 'activation', label: '④ 激活核验' },
]

function SimBar() {
  const [sim, setSim] = useState<{ now_sim: string; auto: boolean } | null>(null)
  useEffect(() => {
    let alive = true
    const load = () => get('/sim').then((s) => alive && setSim(s)).catch(() => {})
    load()
    const t = setInterval(load, 2000)
    return () => { alive = false; clearInterval(t) }
  }, [])

  async function tick(n: number) {
    await runAction(post('/sim/tick', { minutes: n }))
    window.dispatchEvent(new Event('data-changed'))
  }
  async function toggleAuto() {
    try {
      await post('/sim/auto', { enabled: !sim?.auto })
      const s = await get('/sim')
      setSim(s)
    } catch (e: any) { alert(e.message) }
  }

  return (
    <div className="sim-box" title="所有办理时刻都以模拟时钟为准，可手动推进或开启自动走钟">
      <span>🕒 模拟时间</span>
      <b>{sim?.now_sim?.replace('T', ' ') || '—'}</b>
      <button className="btn sm" onClick={() => tick(1)}>+1 分</button>
      <button className="btn sm" onClick={() => tick(5)}>+5 分</button>
      <label style={{ display: 'flex', alignItems: 'center', gap: 4, cursor: 'pointer' }}>
        <input type="checkbox" style={{ width: 'auto' }} checked={!!sim?.auto} onChange={toggleAuto} />
        自动
      </label>
    </div>
  )
}

export default function App() {
  const [me, setMe] = useState<any>(null)
  const [ready, setReady] = useState(false)
  const [tab, setTab] = useState('customer')

  useEffect(() => {
    if (getToken()) {
      get('/me').then((u) => {
        setMe(u)
        if (u.role === 'clerk') setTab('clerk')
        if (u.role === 'network') setTab('network')
      }).catch(() => setToken(null)).finally(() => setReady(true))
    } else setReady(true)
  }, [])

  if (!ready) return <div style={{ display: 'grid', placeItems: 'center', height: '100vh' }}><span className="spinner" /></div>
  if (!me) return <><Login onLogin={(u) => { setMe(u); if (u.role === 'clerk') setTab('clerk'); else if (u.role === 'network') setTab('network') }} /><Toaster /></>

  function logout() {
    setToken(null)
    setMe(null)
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          号卡更换与激活办理平台
          <small>SIM Replacement & Activation · 全虚构适配器演练系统</small>
        </div>
        <nav className="tabs">
          {TABS.map((t) => (
            <button key={t.key} className={`tab ${tab === t.key ? 'active' : ''}`} onClick={() => setTab(t.key)}>
              {t.label}
            </button>
          ))}
        </nav>
        <div className="top-right">
          <SimBar />
          <span style={{ fontSize: 12.5 }}>
            <b>{me.display_name}</b>（{ { admin: '管理员', clerk: '营业员', network: '网络员', customer: '客户' }[me.role] || me.role }）
          </span>
          <button className="btn sm" onClick={logout}>退出</button>
        </div>
      </header>
      <main className="content">
        {tab === 'customer' && <CustomerPage me={me} onGo={(t) => setTab(t)} />}
        {tab === 'clerk' && <ClerkPage me={me} />}
        {tab === 'network' && <NetworkPage me={me} />}
        {tab === 'activation' && <ActivationPage me={me} />}
      </main>
      <Toaster />
    </div>
  )
}
