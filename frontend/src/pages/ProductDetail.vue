<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button, Select, TextInput, toast } from 'frappe-ui'
import { api, money } from '../api'
import AppShell from '../components/AppShell.vue'
import AsyncState from '../components/AsyncState.vue'

interface CyclePrice {
  billing_cycle: string
  price: number
  currency: string
  price_source: string
}

interface Detail {
  name: string
  product_name: string
  product_group: string
  billing_cycle: string
  price: number
  currency: string
  description?: string
  specs: Record<string, number | null>
  options: Array<{ name: string; option_name: string; option_type: string; price_per_unit: number }>
  addons: Array<{ name: string; addon_name: string; price: number }>
  billing_cycles?: CyclePrice[]
}

const route = useRoute()
const router = useRouter()
const name = route.params.name as string
const loading = ref(true)
const error = ref<string | null>(null)
const detail = ref<Detail | null>(null)
const cycle = ref('')
const adding = ref(false)
const qty = ref(1)
const switching = ref(false)

const cycleOptions = computed(() => {
  if (!detail.value) return []
  const list = detail.value.billing_cycles?.length
    ? detail.value.billing_cycles
    : [{ billing_cycle: detail.value.billing_cycle, price: detail.value.price, currency: detail.value.currency, price_source: '' }]
  return list.map((c) => ({
    label: `${c.billing_cycle} — ${money(c.price, c.currency)}`,
    value: c.billing_cycle,
  }))
})

async function load(selectedCycle?: string) {
  loading.value = !detail.value
  error.value = null
  try {
    const params: Record<string, unknown> = { product: name }
    if (selectedCycle) params.billing_cycle = selectedCycle
    detail.value = await api<Detail>('catalog.get_product', params)
    cycle.value = detail.value.billing_cycle
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function onCycleChange(next: string) {
  if (!detail.value || !next || next === detail.value.billing_cycle) return
  // Instant local update when price list already known, then confirm live price.
  const known = detail.value.billing_cycles?.find((c) => c.billing_cycle === next)
  if (known) {
    detail.value = { ...detail.value, billing_cycle: known.billing_cycle, price: known.price, currency: known.currency }
  }
  switching.value = true
  try {
    detail.value = await api<Detail>('catalog.get_product', { product: name, billing_cycle: next })
    cycle.value = detail.value.billing_cycle
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    switching.value = false
  }
}

watch(cycle, (next) => {
  void onCycleChange(next)
})

async function addToCart() {
  adding.value = true
  try {
    await api('orders.cart_add', { product: name, qty: qty.value, billing_cycle: cycle.value || undefined })
    toast.success('Added to cart')
    router.push('/cart')
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    adding.value = false
  }
}

onMounted(() => load())
</script>

<template>
  <AppShell>
    <AsyncState :loading="loading" :error="error" @retry="() => load(cycle || undefined)">
      <template v-if="detail">
        <p class="text-xs text-ink-gray-5">{{ detail.product_group }}</p>
        <h1 class="text-xl font-semibold text-ink-gray-9">{{ detail.product_name }}</h1>
        <p v-if="detail.description" class="mt-2 max-w-2xl text-sm text-ink-gray-6">{{ detail.description }}</p>

        <dl v-if="Object.values(detail.specs || {}).some((v) => v)" class="mt-4 grid grid-cols-2 gap-2 rounded-lg border border-outline-gray-1 bg-surface-white p-4 text-sm md:grid-cols-4">
          <div v-for="(v, k) in detail.specs" :key="k">
            <dt class="text-xs text-ink-gray-5">{{ k }}</dt><dd class="font-medium">{{ v ?? '—' }}</dd>
          </div>
        </dl>

        <div class="mt-4 flex flex-wrap items-end gap-3 rounded-lg border border-outline-gray-1 bg-surface-white p-4">
          <div>
            <label for="pd-cycle" class="mb-1 block text-sm font-medium text-ink-gray-7">Billing cycle</label>
            <Select id="pd-cycle" v-model="cycle" :options="cycleOptions" :disabled="switching" />
          </div>
          <div>
            <label for="pd-qty" class="mb-1 block text-sm font-medium text-ink-gray-7">Quantity</label>
            <TextInput id="pd-qty" v-model.number="qty" type="number" :min="1" :max="100" class="w-24" />
          </div>
          <p class="text-lg font-semibold text-ink-gray-9">{{ money(detail.price, detail.currency) }}</p>
          <Button variant="solid" theme="blue" :loading="adding" @click="addToCart">Add to cart</Button>
        </div>

        <section v-if="detail.addons.length" class="mt-4 rounded-lg border border-outline-gray-1 bg-surface-white p-4" aria-label="Available add-ons">
          <h2 class="text-sm font-medium text-ink-gray-7">Available add-ons</h2>
          <ul class="mt-2 divide-y text-sm">
            <li v-for="a in detail.addons" :key="a.name" class="flex justify-between py-1.5">
              <span>{{ a.addon_name }}</span><span class="font-medium">{{ money(a.price, detail.currency) }}</span>
            </li>
          </ul>
          <p class="mt-2 text-xs text-ink-gray-5">Add-ons can also be attached to a running service later.</p>
        </section>
      </template>
    </AsyncState>
  </AppShell>
</template>
