import { call } from 'frappe-ui'

/** Thin typed wrapper over the Phase 10 portal methods. */
const PREFIX = 'beaverbill.beaverbill.portal.'

export interface ApiFailure {
  message: string
  excType?: string
  status?: number
}

function serverMessage(raw: unknown): string {
  const err = raw as {
    message?: string
    error?: { exc_type?: string; _server_messages?: string }
    response?: { status?: number }
  }
  let message = err?.message || 'Request failed'
  try {
    const packed = err?.error?._server_messages
    if (packed) {
      const parsed = JSON.parse(packed) as Array<string | { message?: string }>
      const first = parsed[0]
      const text = typeof first === 'string' ? JSON.parse(first).message : first?.message
      if (text) message = String(text).replace(/<[^>]*>/g, '')
    }
  } catch {
    /* keep the default message */
  }
  return message
}

export function excType(raw: unknown): string {
  return (raw as { error?: { exc_type?: string } })?.error?.exc_type || ''
}

export function isAuthFailure(raw: unknown): boolean {
  const t = excType(raw)
  return t === 'PermissionError' || t === 'AuthenticationError'
}

export async function api<T>(method: string, params: Record<string, unknown> = {}): Promise<T> {
  try {
    return await call<T>(`${PREFIX}${method}`, params)
  } catch (raw) {
    const failure: ApiFailure = { message: serverMessage(raw), excType: excType(raw) || undefined }
    throw Object.assign(new Error(failure.message), failure)
  }
}

/** Frappe session endpoints (login/logout/reset are core, not portal). */
export async function login(usr: string, pwd: string): Promise<void> {
  await call('login', { usr, pwd })
}

export async function logout(): Promise<void> {
  await call('logout')
}

export async function requestPasswordReset(user: string): Promise<void> {
  await call('frappe.core.doctype.user.user.reset_password', { user })
}

export function money(value: number | null | undefined, currency = 'USD'): string {
  const amount = Number(value || 0)
  try {
    return new Intl.NumberFormat(undefined, { style: 'currency', currency }).format(amount)
  } catch {
    return `${currency} ${amount.toFixed(2)}`
  }
}

export function maskSecret(value: string | null | undefined, visible = 4): string {
  if (!value) return '—'
  if (value.length <= visible) return '••••'
  return `••••${value.slice(-visible)}`
}
