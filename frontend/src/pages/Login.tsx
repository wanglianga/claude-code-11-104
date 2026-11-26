import React, { useState } from 'react'
import { post, setToken } from '../api'
import { runAction } from '../ui'

const ACCOUNTS = [
  { username: 'admin', password: 'admin123', title: '系统管理员（全角色权限，推荐演示）', who: 'admin' },
  { username: 'clerk01', password: 'test1234', title: '营业员 王岚', who: '营业受理 / 身份核验 / 分卡 / 库存' },
  { username: 'net01', password: 'test1234', title: '网络办理员 陈工', who: '准备 / 停旧 / 启新 / 查询 / 模拟钟' },
  { username: '13900001111', password: 'test1234', title: '客户 李明（13900001111）', who: '提交申请 / 核验 / 确认 / 结清' },
]

export default function Login({ onLogin }: { onLogin: (u: any) => void }) {
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('admin123')
  const [loading, setLoading] = useState(false)

  async function submit(e?: React.FormEvent) {
    e?.preventDefault()
    setLoading(true)
    try {
      const r = await post<{ token: string; user: any }>('/auth/login', { username, password })
      setToken(r.token)
      onLogin(r.user)
    } catch (err: any) {
      alert(err.message)
    } finally {
      setLoading(false)
    }
  }

  async function resetDemo() {
    if (!confirm('将清空当前数据并重建虚构演示数据，确定？')) return
    await runAction(post('/test/reset'), '演示数据已重建')
  }

  return (
    <div className="login-wrap">
      <div className="login-card">
        <h1>号卡更换与激活办理平台</h1>
        <div className="tiny">客户申请 · 营业办理 · 网络任务 · 激活核验 ｜ 全套资料均为虚构，不接触真实通信账户</div>

        <div className="acct-grid">
          {ACCOUNTS.map((a) => (
            <button key={a.username} type="button" className="acct"
              onClick={() => { setUsername(a.username); setPassword(a.password) }}>
              <b>{a.title}</b>
              <span className="tiny">{a.who} · 账号 {a.username} / {a.password}</span>
            </button>
          ))}
        </div>

        <form onSubmit={submit}>
          <label className="field"><span>账号</span>
            <input value={username} onChange={(e) => setUsername(e.target.value)} /></label>
          <label className="field"><span>密码</span>
            <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
          <button className="btn primary" style={{ width: '100%', padding: 10 }} disabled={loading}>
            {loading ? '登录中…' : '登 录'}
          </button>
        </form>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 12 }}>
          <span className="tiny">验证脚本：scripts/verify_scenarios.py（80 项断言）</span>
          <button className="btn sm" onClick={resetDemo}>重置虚构数据</button>
        </div>
      </div>
    </div>
  )
}
