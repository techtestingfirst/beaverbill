<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { Button, TextInput, toast } from 'frappe-ui'
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
const cart = ref<Cart>({ items: [], coupon: null, total: 0, currency: 'USD' })
const coupon = ref('')
const busy = ref(false)

async function load() {
  loading.value = true
  error.value = null
  try {
    cart.value = await api<Cart>('orders.get_cart')
    coupon.value = cart.value.coupon || ''
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function removeLine(index: number) {
  await api('orders.cart_remove', { index })
  await load()
}

async function applyCoupon() {
  busy.value = true
  try {
    if (!coupon.value.trim()) {
      await api('orders.cart_coupon', { code: null })
    } else {
      await api('orders.cart_coupon', { code: coupon.value.trim() })
      toast.success('Coupon applied')
    }
    await load()
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    busy.value = false
  }
}

function checkout() {
  router.push('/checkout')
}

onMounted(load)
</script>

<template>
  <AppShell>
    <h1 class="text-xl font-semibold text-ink-gray-9">Cart</h1>
    <AsyncState
      :loading="loading" :error="error" :empty="!loading && !error && cart.items.length === 0"
      empty-title="Your cart is empty" empty-text="Add a product from the catalog to get started." @retry="load"
    >
      <template #empty-action>
        <RouterLink to="/catalog" class="rounded-md bg-surface-blue-2 px-4 py-2 text-sm font-medium text-ink-blue-2">Browse catalog</RouterLink>
      </template>
      <ul class="mt-4 divide-y rounded-lg border border-outline-gray-1 bg-surface-white" aria-label="Cart items">
        <li v-for="(line, i) in cart.items" :key="i" class="flex items-center justify-between gap-3 p-4">
          <div>
            <p class="font-medium">{{ line.product }}</p>
            <p class="text-sm text-ink-gray-5">Qty {{ line.qty }} × {{ money(line.unit_total, cart.currency) }}</p>
          </div>
          <div class="flex items-center gap-3">
            <span class="font-medium">{{ money(line.line_total, cart.currency) }}</span>
            <Button variant="ghost" size="sm" :aria-label="`Remove ${line.product}`" @click="removeLine(i)">Remove</Button>
          </div>
        </li>
      </ul>
      <div class="mt-4 flex flex-wrap items-end gap-2 rounded-lg border border-outline-gray-1 bg-surface-white p-4">
        <div class="flex-1">
          <label for="cart-coupon" class="mb-1 block text-sm font-medium">Coupon code</label>
          <TextInput id="cart-coupon" v-model="coupon" placeholder="SAVE10" autocomplete="off" class="w-full sm:w-56" />
        </div>
        <Button :loading="busy" @click="applyCoupon">{{ coupon ? 'Apply' : 'Clear' }}</Button>
        <p class="w-full text-sm text-ink-gray-5">
          {{ cart.coupon ? `Coupon ${cart.coupon} applied.` : 'No coupon applied.' }}
          Total: <strong class="text-ink-gray-9">{{ money(cart.total, cart.currency) }}</strong>
        </p>
      </div>
      <div class="mt-4 flex justify-end">
        <Button variant="solid" theme="blue" @click="checkout">Proceed to checkout</Button>
      </div>
    </AsyncState>
  </AppShell>
</template>
