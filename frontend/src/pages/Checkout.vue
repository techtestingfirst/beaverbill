<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { Button } from 'frappe-ui'
import { api, money } from '../api'
import AppShell from '../components/AppShell.vue'
import AsyncState from '../components/AsyncState.vue'

const router = useRouter()
const loading = ref(true)
const error = ref<string | null>(null)
const placing = ref(false)
const order = ref<{ order: string; invoice: string; total: number; currency: string } | null>(null)
const cartEmpty = ref(false)

async function load() {
  loading.value = true
  error.value = null
  try {
    const cart = await api<{ items: unknown[]; total: number; currency: string }>('orders.get_cart')
    cartEmpty.value = cart.items.length === 0
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
          <RouterLink :to="`/invoices/${order.invoice}`" class="rounded-md bg-surface-blue-2 px-4 py-2 text-sm font-medium text-ink-blue-2">Pay now</RouterLink>
          <RouterLink to="/services" class="rounded-md border border-outline-gray-2 px-4 py-2 text-sm">View services</RouterLink>
        </div>
      </div>
      <div v-else-if="cartEmpty" class="mt-4 rounded-lg border border-dashed border-outline-gray-2 p-6 text-center text-sm text-ink-gray-5">
        Your cart is empty. <RouterLink to="/catalog" class="text-ink-blue-3 hover:underline">Browse the catalog</RouterLink>.
      </div>
      <div v-else class="mt-4 max-w-lg rounded-lg border border-outline-gray-1 bg-surface-white p-5">
        <h2 class="font-medium">Review and place your order</h2>
        <p class="mt-1 text-sm text-ink-gray-5">Placing the order creates an invoice. You pay in the next step — nothing is charged yet.</p>
        <div class="mt-4 flex gap-2">
          <Button variant="outline" @click="router.push('/cart')">Back to cart</Button>
          <Button variant="solid" theme="blue" :loading="placing" @click="placeOrder">Place order</Button>
        </div>
      </div>
    </AsyncState>
  </AppShell>
</template>
