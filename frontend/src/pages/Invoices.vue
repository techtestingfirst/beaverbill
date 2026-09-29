<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { api, money } from '../api'
import AppShell from '../components/AppShell.vue'
import AsyncState from '../components/AsyncState.vue'
import StatusBadge from '../components/StatusBadge.vue'

interface Invoice {
  name: string
  invoice_date: string
  due_date: string
  status: string
  total_amount: number
  outstanding_amount: number
  currency: string
}

const loading = ref(true)
const error = ref<string | null>(null)
const invoices = ref<Invoice[]>([])
const filter = ref('open')

const visible = computed(() =>
  filter.value === 'all' ? invoices.value : invoices.value.filter((i) => Number(i.outstanding_amount) > 0),
)

const openTotal = computed(() =>
  invoices.value
    .filter((i) => Number(i.outstanding_amount) > 0)
    .reduce((sum, i) => sum + Number(i.outstanding_amount), 0),
)

async function load() {
  loading.value = true
  error.value = null
  try {
    const res = await api<{ invoices: Invoice[] }>('billing.list_invoices')
    invoices.value = res.invoices
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
    <div class="flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-xl font-semibold text-ink-gray-9">Payment center</h1>
        <p v-if="!loading" class="mt-0.5 text-sm text-ink-gray-5">
          Outstanding: <strong class="text-ink-gray-8">{{ money(openTotal, invoices[0]?.currency || 'USD') }}</strong>
        </p>
      </div>
      <div class="flex gap-2 text-sm" role="group" aria-label="Invoice filter">
        <button :class="filter === 'open' ? 'font-medium underline' : ''" @click="filter = 'open'">Open</button>
        <button :class="filter === 'all' ? 'font-medium underline' : ''" @click="filter = 'all'">All</button>
        <RouterLink to="/payment-methods" class="portal-link">Payment methods</RouterLink>
      </div>
    </div>
    <AsyncState
      :loading="loading" :error="error" :empty="!loading && !error && visible.length === 0"
      empty-title="No invoices here" empty-text="New orders and renewals appear here." @retry="load"
    >
      <ul class="mt-4 divide-y rounded-lg border border-outline-gray-1 bg-surface-white" aria-label="Invoices">
        <li v-for="i in visible" :key="i.name" class="flex flex-wrap items-center justify-between gap-2 p-4">
          <div>
            <RouterLink :to="`/invoices/${i.name}`" class="font-medium portal-link">{{ i.name }}</RouterLink>
            <p class="text-xs text-ink-gray-5">Due {{ i.due_date }} · {{ money(i.total_amount, i.currency) }}</p>
          </div>
          <div class="flex items-center gap-3">
            <span class="text-sm font-medium">{{ money(i.outstanding_amount, i.currency) }} due</span>
            <StatusBadge :status="i.status" />
          </div>
        </li>
      </ul>
    </AsyncState>
  </AppShell>
</template>
