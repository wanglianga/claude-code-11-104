/* 临时渲染冒烟：jsdom 挂载真实 React App，代理 fetch 到本机后端。 */
import { JSDOM } from 'jsdom'
import React from 'react'
import { createRoot } from 'react-dom/client'
import { act } from 'react-dom/test-utils'
import App from '../src/App'

const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', {
  url: 'http://localhost:5173/',
  pretendToBeVisual: true,
})
const w: any = dom.window
for (const k of ['window', 'document', 'HTMLElement', 'Element', 'Node',
  'SVGElement', 'localStorage', 'CustomEvent', 'Event', 'MouseEvent', 'getComputedStyle',
  'DOMParser', 'MutationObserver']) {
  try { (globalThis as any)[k] = w[k] } catch { /* 只读全局保留 Node 版本 */ }
}
try {
  Object.defineProperty(globalThis, 'navigator', { value: w.navigator, configurable: true })
} catch { /* 保留 Node 原生 navigator */ }
if (!(globalThis as any).requestAnimationFrame) {
  ;(globalThis as any).requestAnimationFrame = (cb: any) => setTimeout(cb, 0)
  ;(globalThis as any).cancelAnimationFrame = (id: any) => clearTimeout(id)
}

const BACKEND = 'http://127.0.0.1:8000'
const realFetch = globalThis.fetch
function proxiedFetch(input: any, init?: any) {
  const u = typeof input === 'string' ? input : input?.url || String(input)
  const url = u.startsWith('http') ? u : BACKEND + (u.startsWith('/') ? u : '/' + u)
  return realFetch(url, init)
}
;(globalThis as any).fetch = proxiedFetch
w.fetch = proxiedFetch

const fatal: string[] = []
const origErr = console.error
console.error = (...a: any[]) => {
  const msg = a.map((x) => (x?.stack || x?.message || String(x))).join(' ')
  if (/is not a function|Cannot read propert|Element type is invalid|Uncaught|Maximum update depth|failed to render/i.test(msg)) {
    fatal.push(msg.slice(0, 500))
  }
  origErr(...a)
}
w.addEventListener('error', (e: any) => fatal.push('window.error: ' + e.message))

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))
const text = () => w.document.body.textContent || ''
function clickByText(needle: string) {
  const btns = Array.from(w.document.querySelectorAll('button'))
  const b = btns.find((x: any) => (x.textContent || '').includes(needle)) as any
  if (!b) throw new Error('找不到按钮: ' + needle)
  b.click()
}

async function main() {
  const lr = await realFetch(BACKEND + '/api/auth/login', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ username: 'admin', password: 'admin123' }),
  })
  const lj = await lr.json()
  w.localStorage.setItem('simswap_token', lj.token)

  await act(async () => {
    createRoot(w.document.getElementById('root')).render(React.createElement(App))
  })
  await sleep(2500)
  if (!text().includes('客户申请')) throw new Error('外壳/客户页未渲染')
  if (!text().includes('提交换卡申请')) throw new Error('申请表单未渲染')
  console.log('PASS 客户申请页渲染')

  // 左侧订单列表自动选中第一张单，OrderDetail 应渲染
  await sleep(1500)
  if (!text().includes('网络指令')) throw new Error('订单详情指令区未渲染')
  if (!text().includes('回执流水')) throw new Error('回执区未渲染')
  if (!text().includes('仍需办理的任务')) throw new Error('任务区未渲染')
  console.log('PASS 订单详情（时间线/指令/回执/任务）渲染')

  await act(async () => { clickByText('营业办理') })
  await sleep(2000)
  if (!text().includes('卡库存与兼容性')) throw new Error('营业台未渲染')
  console.log('PASS 营业办理页渲染')

  await act(async () => { clickByText('网络任务') })
  await sleep(2000)
  if (!text().includes('网络任务清单')) throw new Error('网络台未渲染')
  if (!text().includes('最近网络指令')) throw new Error('指令表未渲染')
  console.log('PASS 网络任务页渲染')

  await act(async () => { clickByText('激活核验') })
  await sleep(2000)
  if (!text().includes('激活凭据台账')) throw new Error('激活页未渲染')
  console.log('PASS 激活核验页渲染')

  if (fatal.length) {
    console.error('FATAL RUNTIME ERRORS:\n' + fatal.join('\n---\n'))
    process.exit(1)
  }
  console.log('UI_SMOKE_OK')
  process.exit(0)
}
main().catch((e) => { console.error(e); process.exit(1) })
