<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { Button, Select, TextInput, toast } from 'frappe-ui'
import { api, money } from '../api'
import AppShell from '../components/AppShell.vue'
import AsyncState from '../components/AsyncState.vue'

interface CartLine {
  product: string
  qty: number
  unit_total: number
  line_total: number
}
interface Cart {
  items: CartLine[]
  coupon: string | null
  subtotal: number
  discount: number
  tax_total: number
  total: number
  currency: string
}
interface OrderForm {
  name: string
  form_name: string
  template: string
  form_type: string
  require_tos: number
  tos_text?: string
  require_recurring_consent: number
  require_captcha: number
  allow_coupon: number
  require_manual_review: number
}

const router = useRouter()
const loading = ref(true)
const error = ref<string | null>(null)
const placing = ref(false)
const checking = ref(false)
const order = ref<{ order: string; invoice?: string; status?: string; screening?: string; total: number; currency: string } | null>(null)
const cart = ref<Cart>({ items: [], coupon: null, subtotal: 0, discount: 0, tax_total: 0, total: 0, currency: 'USD' })
const cartEmpty = ref(false)
const forms = ref<OrderForm[]>([])
const formName = ref('')
const form = ref<OrderForm | null>(null)
const domainMode = ref('')
const domainName = ref('')
const domainState = ref<string | null>(null)
const tos = ref(false)
const recurring = ref(false)
const captcha = ref(false)
const country = ref('')
const state = ref('')
const addr1 = ref('')
const city = ref('')
const postal = ref('')
const taxId = ref('')
const taxMsg = ref<string | null>(null)
const countries = ref<Array<{ name: string; code?: string }>>([])
const lookingUp = ref(false)

async function load() {
  loading.value = true
  error.value = null
  try {
    const [c, f] = await Promise.all([
      api<Cart>('orders.get_cart'),
      api<{ forms: OrderForm[] }>('order_forms.list_order_forms').catch(() => ({ forms: [] })),
    ])
    cart.value = c
    cartEmpty.value = c.items.length === 0
    try {
      const tp = await api<Record<string, unknown>>('account.get_tax_profile')
      country.value = String(tp.country || '')
      state.value = String(tp.state || '')
      addr1.value = String(tp.address_line1 || '')
      city.value = String(tp.city || '')
      postal.value = String(tp.postal_code || '')
      taxId.value = String(tp.tax_id || '')
    } catch { /* profile optional */ }
    try {
      const cl = await api<{ countries: Array<{ name: string; code?: string }> }>('account.list_countries')
      countries.value = cl.countries
    } catch { /* dropdown optional */ }
    forms.value = f.forms
    if (f.forms.length && !formName.value) formName.value = f.forms[0].name
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function loadForm() {
  if (!formName.value) {
    form.value = null
    return
  }
  try {
    form.value = await api<OrderForm>('order_forms.get_order_form', { form: formName.value })
  } catch (e) {
    toast.error((e as Error).message)
  }
}

async function checkDomain() {
  if (!domainName.value.trim()) {
    toast.error('Enter a domain first.')
    return
  }
  checking.value = true
  domainState.value = null
  try {
    const res = await api<{ domain: string; available: boolean }>('order_forms.check_domain', {
      domain: domainName.value.trim(),
    })
    domainState.value = res.available ? `Available: ${res.domain}` : `Not available: ${res.domain}`
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    checking.value = false
  }
}

function idempotencyKey(): string {
  const bytes = new Uint8Array(12)
  crypto.getRandomValues(bytes)
  return `web-${Date.now()}-${Array.from(bytes).map((b) => b.toString(16).padStart(2, '0')).join('')}`
}

async function saveTaxProfile() {
  taxMsg.value = null
  try {
    const tp = await api<Record<string, unknown>>('account.update_tax_profile', {
      country: country.value || undefined,
      state: state.value || undefined,
      address_line1: addr1.value || undefined,
      city: city.value || undefined,
      postal_code: postal.value || undefined,
      tax_id: taxId.value.trim() || undefined,
    })
    if (tp && tp.tax_id && !tp.tax_id_validated) taxMsg.value = 'Tax ID format not recognized.'
  } catch (e) {
    taxMsg.value = (e as Error).message
  }
}

async function lookupPostal() {
  if (!country.value || postal.value.trim().length < 3 || lookingUp.value) return
  lookingUp.value = true
  taxMsg.value = null
  try {
    const res = await api<{ city: string; state: string; source?: string }>('account.lookup_postal', {
      country: country.value,
      postal_code: postal.value.trim(),
    })
    if (res.city && res.source !== 'manual') {
      city.value = res.city
      if (res.state) state.value = res.state
      taxMsg.value = `City autofilled: ${res.city}`
    } else {
      taxMsg.value = 'Postal code not found — enter city manually.'
    }
  } catch (e) {
    taxMsg.value = 'Autofill unavailable — enter city manually.'
  } finally {
    lookingUp.value = false
  }
}

async function placeOrder() {
  placing.value = true
  error.value = null
  try {
    await saveTaxProfile()
    order.value = await api('orders.checkout', {
      idempotency_key: idempotencyKey(),
      order_form: formName.value || undefined,
      domain_mode: domainMode.value || undefined,
      domain_name: domainName.value.trim() || undefined,
      tos_consented: tos.value || undefined,
      recurring_consented: recurring.value || undefined,
      captcha_verified: captcha.value || undefined,
    })
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    placing.value = false
  }
}

watch(formName, loadForm)
watch(country, () => {
  city.value = ''
  state.value = ''
  postal.value = ''
  taxMsg.value = null
})
onMounted(async () => {
  await load()
  await loadForm()
})
</script>

<template>
  <AppShell>
    <h1 class="text-xl font-semibold text-ink-gray-9">Checkout</h1>
    <AsyncState :loading="loading" :error="error" @retry="load">
      <div v-if="order" role="status" class="mt-4 rounded-lg border border-outline-green-2 bg-surface-green-1 p-5">
        <h2 class="font-medium">Order {{ order.order }} {{ order.screening ? 'under review' : 'confirmed' }}</h2>
        <p v-if="order.screening" class="mt-1 text-sm">Screening: {{ order.screening }}. Staff will approve before payment.</p>
        <p v-else class="mt-1 text-sm">Total {{ money(order.total, order.currency) }}. Invoice {{ order.invoice }} is ready in the payment center.</p>
        <div v-if="!order.screening" class="mt-4 flex flex-wrap gap-2">
          <RouterLink :to="`/invoices/${order.invoice}`" class="portal-tint rounded-md px-4 py-2 text-sm font-medium">Pay now</RouterLink>
          <RouterLink to="/services" class="rounded-md border border-outline-gray-2 px-4 py-2 text-sm">View services</RouterLink>
        </div>
      </div>
      <div v-else-if="cartEmpty" class="mt-4 rounded-lg border border-dashed border-outline-gray-2 p-6 text-center text-sm text-ink-gray-5">
        Your cart is empty. <RouterLink to="/catalog" class="portal-link">Browse the catalog</RouterLink>.
      </div>
      <div v-else class="mt-4 max-w-lg rounded-lg border border-outline-gray-1 bg-surface-white p-5">
        <h2 class="font-medium text-ink-gray-9">Review and place your order</h2>
        <p class="mt-1 text-sm text-ink-gray-5">Placing the order creates an invoice. You pay in the next step — nothing is charged yet.</p>
        <div v-if="forms.length" class="mt-4">
          <label for="order-form" class="mb-1 block text-sm font-medium">Order form</label>
          <Select
            id="order-form" v-model="formName"
            :options="forms.map((f) => ({ label: `${f.form_name} (${f.form_type}, ${f.template})`, value: f.name }))"
            class="w-full"
          />
        </div>
        <ul class="mt-4 divide-y divide-outline-gray-1 border-y border-outline-gray-1" aria-label="Order summary">
          <li v-for="(line, i) in cart.items" :key="i" class="flex items-start justify-between gap-3 py-2.5 text-sm">
            <div>
              <p class="font-medium text-ink-gray-9">{{ line.product }}</p>
              <p class="text-ink-gray-5">Qty {{ line.qty }} × {{ money(line.unit_total, cart.currency) }}</p>
            </div>
            <span class="font-medium text-ink-gray-9">{{ money(line.line_total, cart.currency) }}</span>
          </li>
        </ul>
        <div v-if="!form || form.form_type !== 'general'" class="mt-4 rounded-md border border-outline-gray-1 p-3">
          <p class="text-sm font-medium">Domain step</p>
          <div class="mt-2 flex flex-wrap gap-2 text-sm">
            <label class="flex items-center gap-1"><input v-model="domainMode" type="radio" value="" /> No domain</label>
            <label class="flex items-center gap-1"><input v-model="domainMode" type="radio" value="register" /> Register new</label>
            <label class="flex items-center gap-1"><input v-model="domainMode" type="radio" value="existing" /> Use existing</label>
          </div>
          <div v-if="domainMode" class="mt-2 flex gap-2">
            <TextInput v-model="domainName" placeholder="example.com" autocomplete="off" class="flex-1" />
            <Button :loading="checking" @click="checkDomain">Check</Button>
          </div>
          <p v-if="domainState" role="status" class="mt-1 text-xs text-ink-gray-6">{{ domainState }}</p>
        </div>
        <dl class="mt-3 space-y-1 text-sm">
          <div class="flex justify-between text-ink-gray-6">
            <dt>Subtotal</dt><dd>{{ money(cart.subtotal, cart.currency) }}</dd>
          </div>
          <div class="flex justify-between text-ink-gray-6">
            <dt>{{ cart.coupon ? `Discount (${cart.coupon})` : 'Discount' }}</dt><dd>−{{ money(cart.discount, cart.currency) }}</dd>
          </div>
          <div class="flex justify-between text-ink-gray-6">
            <dt>Tax</dt><dd>{{ money(cart.tax_total, cart.currency) }}</dd>
          </div>
          <div class="flex justify-between text-ink-gray-6">
            <dt>{{ cart.coupon ? `Coupon ${cart.coupon} applied` : 'No coupon applied' }}</dt>
            <dd><RouterLink to="/cart" class="portal-link">Edit</RouterLink></dd>
          </div>
          <div class="flex justify-between pt-1 text-base font-semibold text-ink-gray-9">
            <dt>Total</dt>
            <dd>{{ money(cart.total, cart.currency) }}</dd>
          </div>
        </dl>
        <div v-if="form?.require_tos" class="mt-3 text-sm">
          <label class="flex items-start gap-2">
            <input v-model="tos" type="checkbox" class="mt-1" />
            <span>I agree to the Terms of Service. {{ form.tos_text || '' }}</span>
          </label>
        </div>
        <div v-if="form?.require_recurring_consent" class="mt-2 text-sm">
          <label class="flex items-start gap-2">
            <input v-model="recurring" type="checkbox" class="mt-1" />
            <span>I consent to recurring billing for renewals.</span>
          </label>
        </div>
        <div class="mt-4 rounded-md border border-outline-gray-1 p-3">
          <p class="text-sm font-medium">Billing address (drives tax)</p>
          <div class="mt-2 grid grid-cols-2 gap-2 text-sm">
            <Select
              v-model="country" placeholder="Select country"
              :options="countries.map((c) => ({ label: c.name, value: c.name }))"
              class="col-span-2"
            />
            <TextInput v-model="state" placeholder="State" autocomplete="address-level1" />
            <div class="flex gap-2">
              <TextInput v-model="postal" placeholder="Postal code" autocomplete="postal-code" @blur="lookupPostal" class="flex-1" />
              <Button :loading="lookingUp" @click="lookupPostal">Autofill</Button>
            </div>
            <TextInput v-model="addr1" placeholder="Address line 1" autocomplete="address-line1" class="col-span-2" />
            <TextInput v-model="city" placeholder="City (autofills from postal)" autocomplete="address-level2" />
            <TextInput v-model="taxId" placeholder="Tax ID / VAT (optional)" autocomplete="off" class="col-span-2" />
          </div>
          <p v-if="lookingUp" class="mt-1 text-xs text-ink-gray-5">Looking up city…</p>
          <p v-if="taxMsg" role="status" class="mt-1 text-xs text-ink-gray-6">{{ taxMsg }}</p>
        </div>
        <div v-if="form?.require_captcha" class="mt-2 text-sm">
          <label class="flex items-start gap-2">
            <input v-model="captcha" type="checkbox" class="mt-1" />
            <span>I am not a robot (verification placeholder).</span>
          </label>
        </div>
        <div class="mt-4 flex gap-2">
          <Button variant="outline" @click="router.push('/cart')">Back to cart</Button>
          <Button variant="solid" theme="blue" :loading="placing" @click="placeOrder">Place order</Button>
        </div>
      </div>
    </AsyncState>
  </AppShell>
</template>
