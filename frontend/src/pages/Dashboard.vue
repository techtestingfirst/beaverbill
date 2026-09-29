<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { api, money } from '../api'
import { session } from '../auth'
import AppShell from '../components/AppShell.vue'
import AsyncState from '../components/AsyncState.vue'
import StatusBadge from '../components/StatusBadge.vue'

interface Service {
  name: string
  status: string
  product: string
  ip_address?: string
}
interface Invoice {
  name: string
  status: string
  total_amount: number
  outstanding_amount: number
  currency: string
  due_date: string
}
interface Notice {
  name: string
  subject: string
  created_at: string
}

const loading = ref(true)
const error = ref<string | null>(null)
const services = ref<Service[]>([])
const invoices = ref<Invoice[]>([])
const notices = ref<Notice[]>([])

async function load() {
  loading.value = true
  error.value = null
  try {
    const [dash, inv, feed] = await Promise.all([
      api<{ services: Service[] }>('services.service_dashboard'),
      api<{ invoices: Invoice[] }>('billing.list_invoices'),
      api<{ notifications: Notice[] }>('support.list_notifications'),
    ])
    services.value = dash.services
    invoices.value = inv.invoices.filter((i) => Number(i.outstanding_amount) > 0).slice(0, 5)
    notices.value = feed.notifications.slice(0, 5)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <AppShell>
    <h1 class="text-xl font-semibold text-ink-gray-9">Welcome{{ session.user ? `, ${session.user.split('@')[0]}` : '' }}</h1>
    <p class="mt-0.5 text-sm text-ink-gray-5">Here is an overview of your hosting account.</p>
    <AsyncState :loading="loading" :error="error" @retry="load">
      <div class="mt-6 grid gap-4 md:grid-cols-3">
        <section class="rounded-lg border border-outline-gray-1 bg-surface-white p-4" aria-labelledby="dash-services">
          <h2 id="dash-services" class="text-sm font-medium text-ink-gray-5">Services</h2>
          <p class="mt-1 text-2xl font-semibold">{{ services.length }}</p>
          <ul v-if="services.length" class="mt-3 space-y-2">
            <li v-for="s in services.slice(0, 4)" :key="s.name" class="flex items-center justify-between gap-2 text-sm">
              <RouterLink :to="`/services/${s.name}`" class="truncate portal-link">{{ s.product }}</RouterLink>
              <StatusBadge :status="s.status" />
            </li>
          </ul>
          <RouterLink to="/services" class="mt-3 inline-block text-sm portal-link">View all services</RouterLink>
        </section>
        <section class="rounded-lg border border-outline-gray-1 bg-surface-white p-4" aria-labelledby="dash-billing">
          <h2 id="dash-billing" class="text-sm font-medium text-ink-gray-5">Outstanding invoices</h2>
          <p class="mt-1 text-2xl font-semibold">{{ invoices.length }}</p>
          <ul v-if="invoices.length" class="mt-3 space-y-2">
            <li v-for="i in invoices" :key="i.name" class="flex items-center justify-between gap-2 text-sm">
              <RouterLink :to="`/invoices/${i.name}`" class="portal-link">{{ i.name }}</RouterLink>
              <span class="font-medium">{{ money(i.outstanding_amount, i.currency) }}</span>
            </li>
          </ul>
          <RouterLink to="/invoices" class="mt-3 inline-block text-sm portal-link">Payment center</RouterLink>
        </section>
        <section class="rounded-lg border border-outline-gray-1 bg-surface-white p-4" aria-labelledby="dash-notices">
          <h2 id="dash-notices" class="text-sm font-medium text-ink-gray-5">Latest notices</h2>
          <ul v-if="notices.length" class="mt-3 space-y-2">
            <li v-for="n in notices" :key="n.name" class="text-sm">
              <RouterLink to="/profile#notifications" class="text-ink-gray-8 hover:underline">{{ n.subject }}</RouterLink>
            </li>
          </ul>
          <p v-else class="mt-3 text-sm text-ink-gray-5">No notices. Engine alerts land here too.</p>
          <RouterLink to="/profile#notifications" class="mt-3 inline-block text-sm portal-link">All notifications</RouterLink>
        </section>
      </div>
      <div class="mt-4 flex flex-wrap gap-2">
        <RouterLink to="/catalog" class="portal-tint rounded-md px-4 py-2 text-sm font-medium">Order new service</RouterLink>
        <RouterLink to="/tickets/new" class="rounded-md border border-outline-gray-2 px-4 py-2 text-sm text-ink-gray-7">Open a ticket</RouterLink>
      </div>
    </AsyncState>
  </AppShell>
</template>
