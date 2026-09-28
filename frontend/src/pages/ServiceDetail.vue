<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Button, Dialog, ErrorMessage, Select, TextInput, toast } from 'frappe-ui'
import { api, maskSecret, money } from '../api'
import AppShell from '../components/AppShell.vue'
import AsyncState from '../components/AsyncState.vue'
import StatusBadge from '../components/StatusBadge.vue'

interface Detail {
  name: string
  status: string
  product: string
  billing_cycle?: string
  subscription?: string
  ip_address?: string
  domain?: string
  server_node?: string
  reconciliation_status?: string
  recent_operations: Array<{ name: string; operation_type: string; status: string }>
  addons: Array<{ name: string; addon: string; status: string; price: number; current_period_end?: string }>
}

const route = useRoute()
const name = route.params.name as string
const loading = ref(true)
const error = ref<string | null>(null)
const detail = ref<Detail | null>(null)
const busy = ref<string | null>(null)

// dialogs
const showReset = ref(false)
const showReinstall = ref(false)
const showPlan = ref(false)
const showConsole = ref(false)
const confirmText = ref('')
const ackLoss = ref(false)
const newProduct = ref('')
const products = ref<Array<{ name: string; product_name: string; price: number }>>([])
const planResult = ref<{ request: string; proration_amount: number } | null>(null)
const consoleTicket = ref<{ ticket: string; url: string; expires_in: number } | null>(null)
const usage = ref<{ reported_usage: Record<string, number>; storage_snapshots: Array<Record<string, number | string>> } | null>(null)

const canPower = computed(() => ['Active', 'Suspended'].includes(detail.value?.status || ''))

async function load() {
  loading.value = true
  error.value = null
  try {
    detail.value = await api<Detail>('services.service_detail', { service: name })
    usage.value = await api('services.service_usage', { service: name })
    const catalog = await api<{ products: Array<{ name: string; product_name: string; price: number }> }>(
      'catalog.list_products',
    )
    products.value = catalog.products.filter((p) => p.name !== detail.value?.product)
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function power(action: 'reboot' | 'poweroff' | 'poweron') {
  busy.value = action
  try {
    const res = await api<{ status: string }>('services.power', { service: name, action })
    toast.success(`Power ${action}: ${res.status}`)
    await load()
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    busy.value = null
  }
}

async function openConsole() {
  busy.value = 'console'
  try {
    consoleTicket.value = await api('services.console_url', { service: name })
    showConsole.value = true
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    busy.value = null
  }
}

function copyTicket() {
  if (consoleTicket.value) navigator.clipboard?.writeText(consoleTicket.value.ticket).catch(() => {})
}

async function doReset() {
  busy.value = 'reset'
  try {
    await api('services.password_reset', {
      service: name,
      idempotency_key: `portal-pw-${name}-${Date.now()}`,
      confirm: true,
    })
    toast.success('Password reset dispatched')
    showReset.value = false
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    busy.value = null
  }
}

async function doReinstall() {
  if (confirmText.value.trim().toUpperCase() !== 'REINSTALL' || !ackLoss.value) return
  busy.value = 'reinstall'
  try {
    await api('services.os_reinstall', {
      service: name,
      idempotency_key: `portal-os-${name}-${Date.now()}`,
      confirm: true,
      acknowledge_data_loss: true,
    })
    toast.success('OS reinstall started')
    showReinstall.value = false
    confirmText.value = ''
    ackLoss.value = false
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    busy.value = null
  }
}

async function doPlan() {
  if (!newProduct.value) return
  busy.value = 'plan'
  try {
    planResult.value = await api('services.change_plan', {
      service: name,
      new_product: newProduct.value,
      effective_mode: 'Immediate',
      data_loss_acknowledged: ackLoss.value,
      idempotency_key: `portal-plan-${name}-${newProduct.value}-${Date.now()}`,
    })
    toast.success('Plan change requested')
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    busy.value = null
  }
}

onMounted(load)
</script>

<template>
  <AppShell>
    <AsyncState :loading="loading" :error="error" @retry="load">
      <template v-if="detail">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 class="text-xl font-semibold text-ink-gray-9">{{ detail.product }}</h1>
            <p class="font-mono text-xs text-ink-gray-5">{{ detail.name }} · {{ detail.billing_cycle }}</p>
          </div>
          <StatusBadge :status="detail.status" />
        </div>

        <dl class="mt-4 grid grid-cols-2 gap-3 rounded-lg border border-outline-gray-1 bg-surface-white p-4 text-sm md:grid-cols-4">
          <div><dt class="text-xs text-ink-gray-5">IP address</dt><dd class="font-mono">{{ detail.ip_address || '—' }}</dd></div>
          <div><dt class="text-xs text-ink-gray-5">Domain</dt><dd>{{ detail.domain || '—' }}</dd></div>
          <div><dt class="text-xs text-ink-gray-5">Node</dt><dd>{{ detail.server_node || '—' }}</dd></div>
          <div><dt class="text-xs text-ink-gray-5">Reconciliation</dt><dd>{{ detail.reconciliation_status || '—' }}</dd></div>
        </dl>

        <section class="mt-4 rounded-lg border border-outline-gray-1 bg-surface-white p-4" aria-label="Power controls">
          <h2 class="text-sm font-medium text-ink-gray-7">Power</h2>
          <div class="mt-2 flex flex-wrap gap-2">
            <Button :disabled="!canPower" :loading="busy === 'reboot'" @click="power('reboot')">Reboot</Button>
            <Button :disabled="!canPower" :loading="busy === 'poweroff'" @click="power('poweroff')">Power off</Button>
            <Button :disabled="!canPower" :loading="busy === 'poweron'" @click="power('poweron')">Power on</Button>
            <Button :loading="busy === 'console'" @click="openConsole">Console access</Button>
          </div>
          <p v-if="!canPower" class="mt-2 text-xs text-ink-gray-5">Power controls are available while the service is Active or Suspended.</p>
        </section>

        <section class="mt-4 rounded-lg border border-outline-gray-1 bg-surface-white p-4" aria-label="Dangerous actions">
          <h2 class="text-sm font-medium text-ink-gray-7">Credentials &amp; OS</h2>
          <div class="mt-2 flex flex-wrap gap-2">
            <Button @click="showReset = true">Reset password</Button>
            <Button theme="red" @click="showReinstall = true">Reinstall OS</Button>
            <Button @click="showPlan = true">Change plan</Button>
          </div>
        </section>

        <section class="mt-4 rounded-lg border border-outline-gray-1 bg-surface-white p-4" aria-label="Usage">
          <h2 class="text-sm font-medium text-ink-gray-7">Usage</h2>
          <ul v-if="usage && Object.keys(usage.reported_usage || {}).length" class="mt-2 grid grid-cols-2 gap-2 text-sm md:grid-cols-4">
            <li v-for="(v, k) in usage.reported_usage" :key="k" class="rounded bg-surface-gray-1 px-3 py-2">
              <span class="block text-xs text-ink-gray-5">{{ k }}</span><span class="font-medium">{{ v }}</span>
            </li>
          </ul>
          <p v-else class="mt-2 text-sm text-ink-gray-5">No usage reported yet.</p>
        </section>

        <section class="mt-4 rounded-lg border border-outline-gray-1 bg-surface-white p-4" aria-label="Add-ons">
          <h2 class="text-sm font-medium text-ink-gray-7">Add-ons</h2>
          <ul v-if="detail.addons.length" class="mt-2 divide-y text-sm">
            <li v-for="a in detail.addons" :key="a.name" class="flex items-center justify-between py-2">
              <span>{{ a.addon }} <span class="text-ink-gray-5">· {{ money(a.price) }}</span></span>
              <StatusBadge :status="a.status" />
            </li>
          </ul>
          <p v-else class="mt-2 text-sm text-ink-gray-5">No add-ons. <RouterLink to="/addons" class="text-ink-blue-3 hover:underline">Order one</RouterLink>.</p>
        </section>

        <section class="mt-4 rounded-lg border border-outline-gray-1 bg-surface-white p-4" aria-label="Recent operations">
          <h2 class="text-sm font-medium text-ink-gray-7">Recent operations</h2>
          <ul v-if="detail.recent_operations.length" class="mt-2 divide-y text-sm">
            <li v-for="op in detail.recent_operations" :key="op.name" class="flex items-center justify-between py-1.5">
              <span>{{ op.operation_type }} <span class="font-mono text-xs text-ink-gray-5">{{ op.name }}</span></span>
              <StatusBadge :status="op.status" />
            </li>
          </ul>
          <p v-else class="mt-2 text-sm text-ink-gray-5">No operations yet.</p>
        </section>
      </template>
    </AsyncState>

    <Dialog v-model="showReset" title="Reset password" :options="{ size: 'sm' }">
      <p class="text-sm text-ink-gray-6">This replaces the service credentials immediately. Confirm to continue.</p>
      <template #actions>
        <Button @click="showReset = false">Cancel</Button>
        <Button variant="solid" theme="blue" :loading="busy === 'reset'" @click="doReset">Confirm reset</Button>
      </template>
    </Dialog>

    <Dialog v-model="showReinstall" title="Reinstall OS">
      <div class="space-y-3 text-sm">
        <p role="alert" class="rounded bg-surface-red-1 p-3 text-ink-red-2">Reinstalling wipes <strong>all data</strong> on this service. This cannot be undone.</p>
        <label class="flex items-start gap-2">
          <input v-model="ackLoss" type="checkbox" class="mt-1" aria-label="I understand all data will be wiped" />
          <span>I understand all data will be wiped.</span>
        </label>
        <div>
          <label for="reinstall-confirm" class="mb-1 block font-medium">Type REINSTALL to confirm</label>
          <TextInput id="reinstall-confirm" v-model="confirmText" autocomplete="off" class="w-full" />
        </div>
        <ErrorMessage v-if="ackLoss && confirmText.trim().toUpperCase() !== 'REINSTALL'" message="Type REINSTALL exactly." />
      </div>
      <template #actions>
        <Button @click="showReinstall = false">Cancel</Button>
        <Button
          variant="solid" theme="red" :loading="busy === 'reinstall'"
          :disabled="!ackLoss || confirmText.trim().toUpperCase() !== 'REINSTALL'"
          @click="doReinstall"
        >Wipe and reinstall</Button>
      </template>
    </Dialog>

    <Dialog v-model="showPlan" title="Change plan">
      <div class="space-y-3 text-sm">
        <div>
          <label for="plan-product" class="mb-1 block font-medium">New product</label>
          <Select id="plan-product" v-model="newProduct" :options="products.map((p) => ({ label: `${p.product_name} — ${money(p.price)}`, value: p.name }))" class="w-full" />
        </div>
        <label class="flex items-start gap-2">
          <input v-model="ackLoss" type="checkbox" class="mt-1" aria-label="I accept possible capacity changes from a downgrade" />
          <span>I accept possible capacity changes from a downgrade.</span>
        </label>
        <p v-if="planResult" role="status" class="rounded bg-surface-green-1 p-3">
          Request {{ planResult.request }} created. Proration: {{ money(planResult.proration_amount) }}.
        </p>
      </div>
      <template #actions>
        <Button @click="showPlan = false">Close</Button>
        <Button variant="solid" theme="blue" :loading="busy === 'plan'" :disabled="!newProduct" @click="doPlan">Request change</Button>
      </template>
    </Dialog>

    <Dialog v-model="showConsole" title="Console access">
      <div v-if="consoleTicket" class="space-y-3 text-sm">
        <p role="alert" class="rounded bg-surface-amber-1 p-3">This ticket is single-use and expires in {{ consoleTicket.expires_in }} seconds. Never share it.</p>
        <p>Ticket: <code class="font-mono">{{ maskSecret(consoleTicket.ticket, 6) }}</code></p>
        <div class="flex gap-2">
          <Button @click="copyTicket">Copy ticket</Button>
          <a :href="consoleTicket.url" target="_blank" rel="noopener" class="rounded-md bg-surface-blue-2 px-4 py-1.5 text-sm font-medium text-ink-blue-2">Open console</a>
        </div>
      </div>
    </Dialog>
  </AppShell>
</template>
