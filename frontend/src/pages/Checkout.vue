<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { Button } from 'frappe-ui'
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
  total: number
  currency: string
}

const router = useRouter()
const loading = ref(true)
const error = ref<string | null>(null)
const placing = ref(false)
const order = ref<{ order: string; invoice: string; total: number; currency: string } | null>(null)
const cart = ref<Cart>({ items: [], coupon: null, total: 0, currency: 'USD' })
const cartEmpty = ref(false)

async function load() {
  loading.value = true
  error.value = null
  try {
    cart.value = await api<Cart>('orders.get_cart')
    cartEmpty.value = cart.value.items.length === 0
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

function idempotencyKey(): string {
  const bytes = new Uint8Array(12)
  crypto.getRandomValues(bytes)
  return `web-${Date.now()}-${Array.from(bytes).map((b) => b.toString(16).padStart(2, '0')).join('')}`
}

async function placeOrder() {
  placing.value = true
  error.value = null
  try {
    order.value = await api('orders.checkout', { idempotency_key: idempotencyKey() })
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    placing.value = false
  }
}

onMounted(load)
</script>

<template>
  <AppShell>
    <h1 class="text-xl font-semibold text-ink-gray-9">Checkout</h1>
    <AsyncState :loading="loading" :error="error" @retry="load">
      <div v-if="order" role="status" class="mt-4 rounded-lg border border-outline-green-2 bg-surface-green-1 p-5">
        <h2 class="font-medium">Order {{ order.order }} confirmed</h2>
        <p class="mt-1 text-sm">Total {{ money(order.total, order.currency) }}. Invoice {{ order.invoice }} is ready in the payment center.</p>
        <div class="mt-4 flex flex-wrap gap-2">
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
        <ul class="mt-4 divide-y divide-outline-gray-1 border-y border-outline-gray-1" aria-label="Order summary">
          <li v-for="(line, i) in cart.items" :key="i" class="flex items-start justify-between gap-3 py-2.5 text-sm">
            <div>
              <p class="font-medium text-ink-gray-9">{{ line.product }}</p>
              <p class="text-ink-gray-5">Qty {{ line.qty }} × {{ money(line.unit_total, cart.currency) }}</p>
            </div>
            <span class="font-medium text-ink-gray-9">{{ money(line.line_total, cart.currency) }}</span>
          </li>
        </ul>
        <dl class="mt-3 space-y-1 text-sm">
          <div class="flex justify-between text-ink-gray-6">
            <dt>{{ cart.coupon ? `Coupon ${cart.coupon} applied` : 'No coupon applied' }}</dt>
            <dd><RouterLink to="/cart" class="portal-link">Edit</RouterLink></dd>
          </div>
          <div class="flex justify-between pt-1 text-base font-semibold text-ink-gray-9">
            <dt>Total</dt>
            <dd>{{ money(cart.total, cart.currency) }}</dd>
          </div>
        </dl>
        <div class="mt-4 flex gap-2">
          <Button variant="outline" @click="router.push('/cart')">Back to cart</Button>
          <Button variant="solid" theme="blue" :loading="placing" @click="placeOrder">Place order</Button>
        </div>
      </div>
    </AsyncState>
  </AppShell>
</template>
