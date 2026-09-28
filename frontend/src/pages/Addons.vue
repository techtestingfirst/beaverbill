<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { Button, Dialog, Select, toast } from 'frappe-ui'
import { api, money } from '../api'
import AppShell from '../components/AppShell.vue'
import AsyncState from '../components/AsyncState.vue'
import StatusBadge from '../components/StatusBadge.vue'

interface Addon {
  name: string
  service: string
  addon: string
  status: string
  price: number
  billing_cycle?: string
  current_period_end?: string
}
interface Service {
  name: string
  product: string
  status: string
}

const loading = ref(true)
const error = ref<string | null>(null)
const addons = ref<Addon[]>([])
const services = ref<Service[]>([])
const showOrder = ref(false)
const busy = ref(false)
const order = ref({ service: '', addon: '', catalog: [] as Array<{ name: string; addon_name: string; price: number }> })

async function load() {
  loading.value = true
  error.value = null
  try {
    const [a, s] = await Promise.all([
      api<{ addons: Addon[] }>('assets.my_addons'),
      api<{ services: Service[] }>('services.service_dashboard'),
    ])
    addons.value = a.addons
    services.value = s.services
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function openOrder() {
  if (!services.value.length) {
    toast.error('You need a service before ordering an add-on.')
    return
  }
  order.value.service = services.value[0].name
  order.value.addon = ''
  await loadCatalogForService(order.value.service)
  showOrder.value = true
}

async function loadCatalogForService(service: string) {
  order.value.catalog = []
  order.value.addon = ''
  const svc = services.value.find((s) => s.name === service)
  if (!svc) return
  try {
    const detail = await api<{ addons: Array<{ name: string; addon_name: string; price: number }> }>(
      'catalog.get_product',
      { product: svc.product },
    )
    order.value.catalog = detail.addons || []
  } catch (e) {
    toast.error((e as Error).message)
  }
}

async function placeAddon() {
  if (!order.value.service || !order.value.addon) {
    toast.error('Choose a service and an add-on.')
    return
  }
  busy.value = true
  try {
    await api('assets.order_addon', {
      service: order.value.service,
      addon: order.value.addon,
      idempotency_key: `web-addon-${order.value.service}-${order.value.addon}-${Date.now()}`,
    })
    toast.success('Add-on ordered')
    showOrder.value = false
    await load()
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    busy.value = false
  }
}

async function cancel(name: string, mode: string) {
  try {
    await api('assets.cancel_addon', { addon: name, mode })
    toast.success(mode === 'Immediate' ? 'Add-on cancelled' : 'Add-on will cancel at period end')
    await load()
  } catch (e) {
    toast.error((e as Error).message)
  }
}

onMounted(load)
</script>

<template>
  <AppShell>
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-semibold text-ink-gray-9">Add-ons</h1>
      <Button variant="solid" theme="blue" @click="openOrder">Order add-on</Button>
    </div>
    <AsyncState
      :loading="loading" :error="error" :empty="!loading && !error && addons.length === 0"
      empty-title="No add-ons" empty-text="Attach extra disk, backups, or IPs to a service." @retry="load"
    >
      <ul class="mt-4 divide-y rounded-lg border border-outline-gray-1 bg-surface-white" aria-label="Add-ons">
        <li v-for="a in addons" :key="a.name" class="flex flex-wrap items-center justify-between gap-2 p-4">
          <div>
            <p class="font-medium">{{ a.addon }}</p>
            <p class="text-xs text-ink-gray-5">
              <RouterLink :to="`/services/${a.service}`" class="text-ink-blue-3 hover:underline">{{ a.service }}</RouterLink>
              · {{ money(a.price) }}{{ a.billing_cycle ? `/${a.billing_cycle}` : '' }} · until {{ a.current_period_end || '—' }}
            </p>
          </div>
          <div class="flex items-center gap-2">
            <StatusBadge :status="a.status" />
            <Button v-if="['Active', 'Suspended'].includes(a.status)" size="sm" variant="ghost" @click="cancel(a.name, 'Immediate')">Cancel</Button>
          </div>
        </li>
      </ul>
    </AsyncState>

    <Dialog v-model="showOrder" title="Order add-on">
      <div class="space-y-3 text-sm">
        <div>
          <label for="ao-service" class="mb-1 block font-medium">Service</label>
          <Select
            id="ao-service" v-model="order.service"
            :options="services.map((s) => ({ label: `${s.product} (${s.name})`, value: s.name }))" class="w-full"
            @update:model-value="(v: unknown) => typeof v === 'string' && v && loadCatalogForService(v)"
          />
        </div>
        <div>
          <label for="ao-addon" class="mb-1 block font-medium">Add-on (catalog row ID)</label>
          <Select
            id="ao-addon" v-model="order.addon"
            :options="order.catalog.map((c) => ({ label: `${c.addon_name} — ${money(c.price)}`, value: c.name }))"
            class="w-full"
          />
          <p class="mt-1 text-xs text-ink-gray-5">Add-on catalog rows are listed on each product page.</p>
        </div>
      </div>
      <template #actions>
        <Button @click="showOrder = false">Cancel</Button>
        <Button variant="solid" theme="blue" :loading="busy" @click="placeAddon">Order</Button>
      </template>
    </Dialog>
  </AppShell>
</template>
