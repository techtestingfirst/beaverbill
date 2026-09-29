<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { Select, TextInput } from 'frappe-ui'
import { api, money } from '../api'
import AppShell from '../components/AppShell.vue'
import AsyncState from '../components/AsyncState.vue'

interface Product {
  name: string
  product_name: string
  product_group: string
  billing_cycle: string
  price: number
  currency: string
  description?: string
}

const loading = ref(true)
const error = ref<string | null>(null)
const products = ref<Product[]>([])
const group = ref('')
const query = ref('')

const groups = computed(() => [...new Set(products.value.map((p) => p.product_group))].filter(Boolean))

const visible = computed(() => {
  const q = query.value.trim().toLowerCase()
  return products.value.filter(
    (p) =>
      (!group.value || p.product_group === group.value) &&
      (!q || `${p.product_name} ${p.description || ''}`.toLowerCase().includes(q)),
  )
})

async function load() {
  loading.value = true
  error.value = null
  try {
    const res = await api<{ products: Product[] }>('catalog.list_products')
    products.value = res.products
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
    <h1 class="text-xl font-semibold text-ink-gray-9">Catalog</h1>
    <div class="mt-3 flex flex-wrap gap-2">
      <TextInput v-model="query" type="search" placeholder="Search products…" aria-label="Search products" class="w-full sm:w-64" />
      <Select
        v-model="group"
        :options="[{ label: 'All groups', value: '' }, ...groups.map((g) => ({ label: g, value: g }))]"
        aria-label="Filter by group"
      />
    </div>
    <AsyncState
      :loading="loading" :error="error" :empty="!loading && !error && visible.length === 0"
      empty-title="No products match" empty-text="Try a different search or group." @retry="load"
    >
      <ul class="mt-4 grid gap-3 md:grid-cols-2 lg:grid-cols-3" aria-label="Products">
        <li v-for="p in visible" :key="p.name" class="flex flex-col rounded-lg border border-outline-gray-1 bg-surface-white p-4">
          <p class="text-xs text-ink-gray-5">{{ p.product_group }} · {{ p.billing_cycle }}</p>
          <RouterLink :to="`/catalog/${p.name}`" class="mt-1 font-medium portal-link">{{ p.product_name }}</RouterLink>
          <p v-if="p.description" class="mt-1 line-clamp-2 text-sm text-ink-gray-6">{{ p.description }}</p>
          <p class="mt-auto pt-3 text-lg font-semibold">{{ money(p.price, p.currency) }}</p>
        </li>
      </ul>
    </AsyncState>
  </AppShell>
</template>
