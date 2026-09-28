import { reactive } from 'vue'
import { api, login as frappeLogin, logout as frappeLogout } from './api'

export interface Session {
  loaded: boolean
  user: string | null
  customer: string | null
  roles: string[]
}

export const session = reactive<Session>({ loaded: false, user: null, customer: null, roles: [] })

export async function refreshSession(): Promise<Session> {
  try {
    const status = await api<{ user: string; customer: string | null; roles: string[] }>(
      'account.session_status',
    )
    session.user = status.user
    session.customer = status.customer
    session.roles = status.roles || []
  } catch {
    session.user = null
    session.customer = null
    session.roles = []
  }
  session.loaded = true
  return session
}

export function isLoggedIn(): boolean {
  return !!session.user && session.user !== 'Guest'
}

export async function login(usr: string, pwd: string): Promise<void> {
  await frappeLogin(usr, pwd)
  await refreshSession()
}

export async function logout(): Promise<void> {
  await frappeLogout()
  session.user = null
  session.customer = null
  session.roles = []
  session.loaded = true
}

export async function signup(fullName: string, email: string, password: string) {
  return api<{ user: string; customer: string; verification_sent: boolean }>('public.signup', {
    full_name: fullName,
    email,
    password,
  })
}

export async function verifyEmail(token: string) {
  return api<{ user: string; verified: boolean }>('public.verify_email', { token })
}
