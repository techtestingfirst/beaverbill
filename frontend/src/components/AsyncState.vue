<script setup lang="ts">
import { Button, ErrorMessage, LoadingIndicator } from 'frappe-ui'

withDefaults(
  defineProps<{
    loading: boolean
    error?: string | null
    empty?: boolean
    emptyTitle?: string
    emptyText?: string
    loadingText?: string
  }>(),
  { error: null, empty: false, emptyTitle: 'Nothing here yet', emptyText: '', loadingText: 'Loading…' },
)

defineEmits<{ (e: 'retry'): void }>()
</script>

<template>
  <div v-if="loading" role="status" aria-live="polite" class="flex items-center gap-2 py-10 text-ink-gray-5">
    <LoadingIndicator class="h-5 w-5" />
    <span>{{ loadingText }}</span>
  </div>
  <div v-else-if="error" role="alert" class="space-y-3 rounded-lg border border-outline-red-2 bg-surface-red-1 p-4">
    <ErrorMessage :message="error" />
    <Button variant="outline" size="sm" @click="$emit('retry')">Try again</Button>
  </div>
  <div v-else-if="empty" class="rounded-lg border border-dashed border-outline-gray-2 px-6 py-10 text-center">
    <p class="text-base font-medium text-ink-gray-7">{{ emptyTitle }}</p>
    <p v-if="emptyText" class="mt-1 text-sm text-ink-gray-5">{{ emptyText }}</p>
    <div class="mt-4"><slot name="empty-action" /></div>
  </div>
  <slot v-else />
</template>
