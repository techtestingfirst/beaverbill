<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Button, Dialog, ErrorMessage, Select, Switch, TextInput, toast } from 'frappe-ui'
import { api, maskSecret } from '../api'
import AppShell from '../components/AppShell.vue'
import AsyncState from '../components/AsyncState.vue'

interface Method {
  name: string
  gateway: string
  brand?: string
  last4?: string
  exp_month?: string
  exp_year?: string
  is_default?: number
}

const loading = ref(true)
const error = ref<string | null>(null)
const methods = ref<Method[]>([])
const gateways = ref<Array<{ name: string }>>([])
const showAdd = ref(false)
const busy = ref(false)
const formError = ref<string | null>(null)
const form = ref({ gateway: '', token: '', brand: '', last4: '', exp_month: '', exp_year: '', make_default: false })

async function load() {
  loading.value = true
  error.value = null
  try {
    const [pm, gw] = await Promise.all([
      api<{ methods: Method[] }>('billing.list_payment_methods'),
      api<{ gateways: Array<{ name: string }> }>('billing.list_gateways').catch(() => ({ gateways: [] })),
    ])
    methods.value = pm.methods
    gateways.value = gw.gateways
    if (gw.gateways.length && !form.value.gateway) form.value.gateway = gw.gateways[0].name
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function add() {
  formError.value = null
  if (!form.value.gateway || !form.value.token.trim()) {
    formError.value = 'Choose a gateway and paste the token your gateway issued.'
    return
  }
  busy.value = true
  try {
    await api('billing.add_payment_method', {
      gateway: form.value.gateway,
      token_reference: form.value.token.trim(),
      brand: form.value.brand || undefined,
      last4: form.value.last4 || undefined,
      exp_month: form.value.exp_month || undefined,
      exp_year: form.value.exp_year || undefined,
      make_default: form.value.make_default,
    })
    toast.success('Payment method saved')
    showAdd.value = false
    form.value = { gateway: form.value.gateway, token: '', brand: '', last4: '', exp_month: '', exp_year: '', make_default: false }
    await load()
  } catch (e) {
    formError.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

async function remove(name: string) {
  try {
    await api('billing.remove_payment_method', { name })
    toast.success('Payment method removed')
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
      <h1 class="text-xl font-semibold text-ink-gray-9">Payment methods</h1>
      <Button variant="solid" theme="blue" @click="showAdd = true">Add method</Button>
    </div>
    <p class="mt-1 text-sm text-ink-gray-5">We store only gateway tokens — never card numbers.</p>
    <AsyncState
      :loading="loading" :error="error" :empty="!loading && !error && methods.length === 0"
      empty-title="No saved methods" empty-text="Save a gateway token to check out faster." @retry="load"
    >
      <ul class="mt-4 divide-y rounded-lg border border-outline-gray-1 bg-surface-white" aria-label="Saved payment methods">
        <li v-for="m in methods" :key="m.name" class="flex items-center justify-between gap-3 p-4">
          <div>
            <p class="font-medium">{{ m.brand || 'Card' }} •••• {{ m.last4 || '––––' }}</p>
            <p class="font-mono text-xs text-ink-gray-5">{{ m.gateway }} · {{ m.is_default ? 'default' : 'expires ' + (m.exp_month || '–') + '/' + (m.exp_year || '–') }}</p>
          </div>
          <Button variant="ghost" size="sm" :aria-label="`Remove ${m.brand || 'card'} ending ${m.last4 || ''}`" @click="remove(m.name)">Remove</Button>
        </li>
      </ul>
    </AsyncState>

    <Dialog v-model="showAdd" title="Add payment method">
      <div class="space-y-3 text-sm">
        <p class="rounded bg-surface-amber-1 p-3">Paste the token from your gateway checkout — never type a card number here.</p>
        <div>
          <label for="pm-gateway" class="mb-1 block font-medium">Gateway</label>
          <Select id="pm-gateway" v-model="form.gateway" :options="gateways.map((g) => ({ label: g.name, value: g.name }))" class="w-full" />
        </div>
        <div>
          <label for="pm-token" class="mb-1 block font-medium">Gateway token</label>
          <TextInput id="pm-token" v-model="form.token" autocomplete="off" placeholder="tok_…" class="w-full" />
        </div>
        <div class="grid grid-cols-2 gap-2">
          <div>
            <label for="pm-brand" class="mb-1 block font-medium">Brand (optional)</label>
            <TextInput id="pm-brand" v-model="form.brand" class="w-full" />
          </div>
          <div>
            <label for="pm-last4" class="mb-1 block font-medium">Last 4 (optional)</label>
            <TextInput id="pm-last4" v-model="form.last4" inputmode="numeric" maxlength="4" class="w-full" />
          </div>
        </div>
        <label class="flex items-center gap-2"><Switch v-model="form.make_default" /> Make default</label>
        <ErrorMessage v-if="formError" :message="formError" />
        <p class="text-xs text-ink-gray-5">Preview: {{ maskSecret(form.token || null, 6) }}</p>
      </div>
      <template #actions>
        <Button @click="showAdd = false">Cancel</Button>
        <Button variant="solid" theme="blue" :loading="busy" @click="add">Save method</Button>
      </template>
    </Dialog>
  </AppShell>
</template>
