<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button } from 'frappe-ui'
import { api, money } from '../api'
import { isLoggedIn, logout, session } from '../auth'

const router = useRouter()
const route = useRoute()
const unread = ref(0)
const mobileOpen = ref(false)

const links = [
  { to: '/', label: 'Dashboard' },
  { to: '/services', label: 'Services' },
  { to: '/catalog', label: 'Catalog' },
  { to: '/cart', label: 'Cart' },
  { to: '/invoices', label: 'Invoices' },
  { to: '/domains', label: 'Domains' },
  { to: '/backups', label: 'Backups' },
  { to: '/addons', label: 'Add-ons' },
  { to: '/tickets', label: 'Tickets' },
  { to: '/profile', label: 'Profile' },
]

const isActive = (to: string) =>
  to === '/' ? route.path === '/' : route.path === to || route.path.startsWith(`${to}/`)

async function loadUnread() {
  if (!isLoggedIn()) return
  try {
    const res = await api<{ unread: number }>('support.unread_count')
    unread.value = res.unread
  } catch {
    /* notifications are best-effort in the shell */
  }
}

const dueTotal = ref<string | null>(null)
async function loadDue() {
  if (!isLoggedIn()) return
  try {
    const res = await api<{ invoices: Array<{ status: string; outstanding_amount: number; currency: string }> }>(
      'billing.list_invoices',
    )
    const due = res.invoices
      .filter((i) => ['Issued', 'Partially Paid', 'Overdue'].includes(i.status))
      .reduce((sum, i) => sum + Number(i.outstanding_amount || 0), 0)
    dueTotal.value = due > 0 ? money(due, res.invoices[0]?.currency || 'USD') : null
  } catch {
    dueTotal.value = null
  }
}

async function signOut() {
  await logout()
  router.push('/login')
}

onMounted(() => {
  loadUnread()
  loadDue()
})
</script>

<template>
  <div class="min-h-screen bg-surface-base text-ink-gray-8">
    <a href="#main" class="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface-white focus:px-3 focus:py-2">
      Skip to content
    </a>
    <!-- Desktop sidebar -->
    <aside class="fixed inset-y-0 left-0 hidden w-60 flex-col border-r border-outline-gray-1 bg-surface-white md:flex" aria-label="Primary">
      <div class="px-5 pb-2 pt-5">
        <RouterLink to="/" class="text-lg font-semibold text-ink-gray-9">BeaverBill</RouterLink>
        <p v-if="session.customer" class="mt-0.5 truncate text-xs text-ink-gray-5">{{ session.user }}</p>
      </div>
      <nav class="flex-1 space-y-0.5 overflow-y-auto px-3 py-2">
        <RouterLink
          v-for="link in links"
          :key="link.to"
          :to="link.to"
          :aria-current="isActive(link.to) ? 'page' : undefined"
          class="flex items-center justify-between rounded-md px-3 py-2 text-sm"
          :class="isActive(link.to) ? 'bg-surface-gray-2 font-medium text-ink-gray-9' : 'text-ink-gray-6 hover:bg-surface-gray-1'"
        >
          <span>{{ link.label }}</span>
          <span
            v-if="link.to === '/profile' && unread > 0"
            class="rounded-full portal-tint px-2 text-xs font-medium"
            :aria-label="`${unread} unread notifications`"
          >{{ unread }}</span>
        </RouterLink>
      </nav>
      <div class="border-t border-outline-gray-1 p-3">
        <p v-if="dueTotal" class="px-2 pb-2 text-xs text-ink-gray-5">
          Due now: <span class="font-medium text-ink-gray-8">{{ dueTotal }}</span>
        </p>
        <Button variant="ghost" class="w-full" @click="signOut">Log out</Button>
      </div>
    </aside>

    <!-- Mobile top bar -->
    <header class="sticky top-0 z-30 border-b border-outline-gray-1 bg-surface-white md:hidden">
      <div class="flex items-center justify-between px-4 py-3">
        <RouterLink to="/" class="font-semibold text-ink-gray-9">BeaverBill</RouterLink>
        <div class="flex items-center gap-2">
          <RouterLink to="/cart" class="rounded-md px-2 py-1 text-sm text-ink-gray-6" aria-label="Cart">Cart</RouterLink>
          <Button variant="ghost" size="sm" :aria-expanded="mobileOpen" aria-controls="mobile-nav" @click="mobileOpen = !mobileOpen">
            {{ mobileOpen ? 'Close' : 'Menu' }}
          </Button>
        </div>
      </div>
      <nav v-if="mobileOpen" id="mobile-nav" class="grid grid-cols-2 gap-1 px-4 pb-3" aria-label="Primary">
        <RouterLink
          v-for="link in links"
          :key="link.to"
          :to="link.to"
          class="rounded-md px-3 py-2 text-sm"
          :class="isActive(link.to) ? 'bg-surface-gray-2 font-medium' : 'text-ink-gray-6'"
          @click="mobileOpen = false"
        >
          {{ link.label }}{{ link.to === '/profile' && unread > 0 ? ` (${unread})` : '' }}
        </RouterLink>
        <button class="rounded-md px-3 py-2 text-left text-sm text-ink-gray-6" @click="signOut">Log out</button>
      </nav>
    </header>

    <div class="md:pl-60">
      <main id="main" class="mx-auto w-full max-w-5xl px-4 py-6 md:px-8" tabindex="-1">
        <slot />
      </main>
    </div>
  </div>
</template>
