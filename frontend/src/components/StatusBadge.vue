<script setup lang="ts">
import { computed } from 'vue'
import { Badge } from 'frappe-ui'

const props = defineProps<{ status: string | null | undefined }>()

type Theme = 'gray' | 'blue' | 'green' | 'amber' | 'red' | 'violet'

const theme = computed<Theme>(() => {
  const s = (props.status || '').toLowerCase()
  if (['active', 'paid', 'succeeded', 'completed', 'matched', 'success', 'verified'].includes(s))
    return 'green'
  if (['pending', 'queued', 'retrying', 'processing', 'in progress', 'renewal pending', 'transfer pending'].includes(s))
    return 'blue'
  if (['expired', 'expiring', 'grace period', 'suspended', 'past due', 'overdue', 'mismatched', 'unknown'].includes(s))
    return 'amber'
  if (['failed', 'error', 'terminated', 'cancelled', 'expired card', 'chargeback'].includes(s)) return 'red'
  if (['redemption', 'manual review'].includes(s)) return 'violet'
  return 'gray'
})
</script>

<template>
  <Badge :theme="theme">{{ status || '—' }}</Badge>
</template>
