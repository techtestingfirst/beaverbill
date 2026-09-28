<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { TextInput } from 'frappe-ui'
import { api } from '../api'
import AppShell from '../components/AppShell.vue'
import AsyncState from '../components/AsyncState.vue'
import StatusBadge from '../components/StatusBadge.vue'

interface Service {
  name: string
  status: string
  product: string
  billing_cycle?: string
  ip_address?: string
  domain?: string
}

const loading = ref(true)
const error = ref<string | null>(null)
const services = ref<Service[]>([])
const filter = ref('')

const visible = computed(() => {
  const q = filter.value.trim().toLowerCase()
  if (!q) return services.value
  return services.value.filter((s) =>
    [s.name, s.product, s.status, s.ip_address || '', s.domain || ''].join(' ').toLowerCase().includes(q),
  )
})

async function load() {
  loading.value = true
  error.value = null
  try {
    const res = await api<{ services: Service[] }>('services.service_dashboard')
    services.value = res.services
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
      <h1 class="text-xl font-semibold text-ink-gray-9">Services</h1>
      <TextInput v-model="filter" type="search" placeholder="Filter services…" aria-label="Filter services" class="w-full sm:w-64" />
    </div>
    <AsyncState
      :loading="loading" :error="error" :empty="!loading && !error && visible.length === 0"
      empty-title="No services found" empty-text="Order your first service from the catalog."
      @retry="load"
    >
      <template #empty-action>
        <RouterLink to="/catalog" class="rounded-md bg-surface-blue-2 px-4 py-2 text-sm font-medium text-ink-blue-2">Browse catalog</RouterLink>
      </template>
      <ul class="mt-4 grid gap-3 md:grid-cols-2" aria-label="Services">
        <li v-for="s in visible" :key="s.name" class="rounded-lg border border-outline-gray-1 bg-surface-white p-4">
          <div class="flex items-start justify-between gap-2">
            <div>
              <RouterLink :to="`/services/${s.name}`" class="font-medium text-ink-blue-3 hover:underline">{{ s.product }}</RouterLink>
              <p class="mt-0.5 font-mono text-xs text-ink-gray-5">{{ s.name }}</p>
            </div>
            <StatusBadge :status="s.status" />
          </div>
          <dl class="mt-3 grid grid-cols-2 gap-2 text-sm">
            <div><dt class="text-xs text-ink-gray-5">IP</dt><dd class="font-mono">{{ s.ip_address || '—' }}</dd></div>
            <div><dt class="text-xs text-ink-gray-5">Cycle</dt><dd>{{ s.billing_cycle || '—' }}</dd></div>
          </dl>
        </li>
      </ul>
    </AsyncState>
  </AppShell>
</template>
