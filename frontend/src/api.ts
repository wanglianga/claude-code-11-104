// 轻量 API 客户端：token 存 localStorage，错误抛出带 code/message
const TOKEN_KEY = 'simswap_token'

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(t: string | null) {
  if (t) localStorage.setItem(TOKEN_KEY, t)
  else localStorage.removeItem(TOKEN_KEY)
}

export class ApiError extends Error {
  code: string
  status: number
  extra: any
  constructor(status: number, body: any) {
    super(body?.error?.message || `请求失败 ${status}`)
    this.status = status
    this.code = body?.error?.code || 'ERROR'
    this.extra = body?.error?.extra
  }
}

export async function api<T = any>(method: string, path: string, body?: any): Promise<T> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const tok = getToken()
  if (tok) headers.Authorization = `Bearer ${tok}`
  const r = await fetch(`/api${path}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  let data: any = null
  try {
    data = await r.json()
  } catch {
    /* 非 JSON */
  }
  if (!r.ok) throw new ApiError(r.status, data)
  return data as T
}

export const get = <T = any>(p: string) => api<T>('GET', p)
export const post = <T = any>(p: string, body?: any) => api<T>('POST', p, body ?? {})

export function notifyChanged() {
  window.dispatchEvent(new Event('data-changed'))
}
