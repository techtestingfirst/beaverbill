<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button, Dialog, Select, toast } from 'frappe-ui'
import { api, money } from '../api'
import AppShell from '../components/AppShell.vue'
import AsyncState from '../components/AsyncState.vue'
import StatusBadge from '../components/StatusBadge.vue'

interface Invoice {
  name: string
  status: string
  invoice_date: string
  due_date: string
  total_amount: number
  paid_amount: number
  outstanding_amount: number
  currency: string
  items: Array<{ description: string; qty: number; unit_price: number; line_total: number }>
}
interface Method {
  name: string
  gateway: string
  brand?: string
  last4?: string
}
interface Gateway {
  name: string
}

const route = useRoute()
const router = useRouter()
const name = route.params.name as string
const loading = ref(true)
const error = ref<string | null>(null)
const invoice = ref<Invoice | null>(null)
const showPay = ref(false)
const gateways = ref<Gateway[]>([])
const methods = ref<Method[]>([])
const gateway = ref('')
const method = ref('')
const paying = ref(false)
const downloading = ref(false)
const syncing = ref(false)

async function load() {
  loading.value = true
  error.value = null
  try {
    invoice.value = await api<Invoice>('billing.get_invoice', { name })
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function openPay() {
  showPay.value = true
  try {
    const [gw, pm] = await Promise.all([
      api<{ gateways: Gateway[] }>('billing.list_gateways').catch(() => ({ gateways: [] })),
      api<{ methods: Method[] }>('billing.list_payment_methods'),
    ])
    gateways.value = gw.gateways
    methods.value = pm.methods
    if (gw.gateways.length && !gateway.value) gateway.value = gw.gateways[0].name
  } catch (e) {
    toast.error((e as Error).message)
  }
}

async function syncPayments() {
  syncing.value = true
  try {
    const res = await api<{ status: string; provider_status: string; detail?: string }>('billing.sync_latest_payment', { invoice: name })
    if (res.status === 'Captured') {
      toast.success('Payment verified and applied')
    } else {
      toast.message(res.detail || `Provider status: ${res.provider_status}`)
    }
    await load()
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    syncing.value = false
  }
}

async function downloadPdf() {  downloading.value = true
  try {
    const res = await api<{ pdf_url: string }>('billing.invoice_pdf', { name })
    window.open(res.pdf_url, '_blank', 'noopener')
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    downloading.value = false
  }
}

async function pay() {
  if (!gateway.value) {
    toast.error('Choose a payment gateway.')
    return
  }
  paying.value = true
  try {
    const res = await api<{ payment: string; status: string; payment_url?: string }>('billing.pay_invoice', {
      invoice: name,
      gateway: gateway.value,
      payment_method: method.value || undefined,
      idempotency_key: `web-pay-${name}-${Date.now()}`,
    })
    if (res.payment_url) {
      // Provider checkout is a server page at site root (/razorpay_checkout).
      // Navigate by token only: keeps the customer's current host:port (local
      // DNS, LAN IP, port maps) and never carries the /beaverbill SPA base,
      // which multisite answers with 404.
      try {
        const u = new URL(res.payment_url, window.location.origin)
        const token = u.searchParams.get('token')
        window.location.href = token
          ? `/razorpay_checkout?token=${encodeURIComponent(token)}`
          : `${u.pathname}${u.search}${u.hash}`.replace(/^\/beaverbill(?=\/)/, '')
      } catch {
        window.location.href = res.payment_url
      }
      return
    }
    toast.success(`Payment ${res.payment} is ${res.status}`)
    showPay.value = false
    await load()
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    paying.value = false
  }
}

onMounted(async () => {
  await load()
  // Returning from provider checkout (?just_paid=1): close the loop without
  // depending on the checkout callback. Runs once, then cleans the URL.
  if (route.query.just_paid && invoice.value && invoice.value.outstanding_amount > 0 && !syncing.value) {
    router.replace({ path: route.path, query: {} })
    await syncPayments()
  }
})
</script>

<template>
  <AppShell>
    <AsyncState :loading="loading" :error="error" @retry="load">
      <template v-if="invoice">
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 class="text-xl font-semibold text-ink-gray-9">{{ invoice.name }}</h1>
            <p class="text-sm text-ink-gray-5">Issued {{ invoice.invoice_date }} · due {{ invoice.due_date }}</p>
          </div>
          <StatusBadge :status="invoice.status" />
        </div>
        <div class="mt-4 overflow-x-auto rounded-lg border border-outline-gray-1 bg-surface-white">
          <table class="w-full text-sm">
            <caption class="sr-only">Invoice lines</caption>
            <thead>
              <tr class="border-b border-outline-gray-1 text-left text-xs text-ink-gray-5">
                <th scope="col" class="px-4 py-2">Description</th>
                <th scope="col" class="px-4 py-2 text-right">Qty</th>
                <th scope="col" class="px-4 py-2 text-right">Total</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(line, i) in invoice.items" :key="i" class="border-b border-outline-gray-1 last:border-0">
                <td class="px-4 py-2">{{ line.description }}</td>
                <td class="px-4 py-2 text-right">{{ line.qty }}</td>
                <td class="px-4 py-2 text-right">{{ money(line.line_total, invoice.currency) }}</td>
              </tr>
            </tbody>
            <tfoot>
              <tr class="font-medium">
                <td class="px-4 py-2" colspan="2">Outstanding</td>
                <td class="px-4 py-2 text-right">{{ money(invoice.outstanding_amount, invoice.currency) }}</td>
              </tr>
            </tfoot>
          </table>
        </div>
        <div class="mt-4 flex flex-wrap gap-2">
          <Button v-if="invoice.outstanding_amount > 0" variant="solid" theme="blue" @click="openPay">Pay now</Button>
          <Button v-if="invoice.outstanding_amount > 0" @click="syncPayments" :loading="syncing" title="Paid at the provider but invoice still shows unpaid? Pull the latest provider status.">Verify payment</Button>
          <Button @click="downloadPdf" :loading="downloading">Download PDF</Button>
        </div>
      </template>
    </AsyncState>

    <Dialog v-model="showPay" title="Pay invoice">
      <div class="space-y-3 text-sm">
        <div>
          <label for="pay-gateway" class="mb-1 block font-medium">Gateway</label>
          <Select
            id="pay-gateway" v-model="gateway"
            :options="gateways.map((g) => ({ label: g.name, value: g.name }))"
            class="w-full"
          />
          <p v-if="!gateways.length" class="mt-1 text-xs text-ink-gray-5">No gateways available right now.</p>
        </div>
        <div>
          <label for="pay-method" class="mb-1 block font-medium">Saved method (optional)</label>
          <Select
            id="pay-method" v-model="method"
            :options="[{ label: 'One-time payment', value: '' }, ...methods.filter((m) => !gateway || m.gateway === gateway).map((m) => ({ label: `${m.brand || 'Card'} •••• ${m.last4 || ''}`, value: m.name }))]"
            class="w-full"
          />
        </div>
      </div>
      <template #actions>
        <Button @click="showPay = false">Cancel</Button>
        <Button variant="solid" theme="blue" :loading="paying" @click="pay">Pay {{ invoice ? money(invoice.outstanding_amount, invoice.currency) : '' }}</Button>
      </template>
    </Dialog>
  </AppShell>
</template>
