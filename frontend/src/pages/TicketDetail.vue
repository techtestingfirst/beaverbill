<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Button, Textarea, toast } from 'frappe-ui'
import { api } from '../api'
import AppShell from '../components/AppShell.vue'
import AsyncState from '../components/AsyncState.vue'
import StatusBadge from '../components/StatusBadge.vue'

interface Detail {
  ticket: string
  subject: string
  status: string
  portal_status?: string
  priority?: string
  description: string
  team?: string
  links?: { service?: string; order?: string; invoice?: string; domain?: string }
  sla?: { sla?: string; response_by?: string; resolution_by?: string; agreement_status?: string }
  comments: Array<{ name: string; content: string; commented_by?: string; owner?: string; creation: string; kind?: string }>
}

const route = useRoute()
const name = route.params.name as string
const loading = ref(true)
const error = ref<string | null>(null)
const detail = ref<Detail | null>(null)
const reply = ref('')
const busy = ref(false)

async function load() {
  loading.value = true
  error.value = null
  try {
    detail.value = await api<Detail>('support.ticket_detail', { ticket: name })
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function send() {
  if (!reply.value.trim()) return
  busy.value = true
  try {
    await api('support.ticket_reply', { ticket: name, message: reply.value.trim() })
    reply.value = ''
    toast.success('Reply sent')
    await load()
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <AppShell>
    <AsyncState :loading="loading" :error="error" @retry="load">
      <template v-if="detail">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h1 class="text-xl font-semibold text-ink-gray-9">{{ detail.subject }}</h1>
          <StatusBadge :status="detail.portal_status || detail.status" />
        </div>
        <p class="font-mono text-xs text-ink-gray-5">{{ detail.ticket }}</p>
        <dl v-if="detail.links && (detail.links.service || detail.links.order || detail.links.invoice || detail.links.domain)" class="mt-3 flex flex-wrap gap-x-4 gap-y-1 rounded-lg border border-outline-gray-1 bg-surface-white p-3 text-sm" aria-label="Linked records">
          <div v-if="detail.links.service"><dt class="inline text-xs text-ink-gray-5">Service </dt><dd class="inline font-mono">{{ detail.links.service }}</dd></div>
          <div v-if="detail.links.order"><dt class="inline text-xs text-ink-gray-5">Order </dt><dd class="inline font-mono">{{ detail.links.order }}</dd></div>
          <div v-if="detail.links.invoice"><dt class="inline text-xs text-ink-gray-5">Invoice </dt><dd class="inline font-mono">{{ detail.links.invoice }}</dd></div>
          <div v-if="detail.links.domain"><dt class="inline text-xs text-ink-gray-5">Domain </dt><dd class="inline font-mono">{{ detail.links.domain }}</dd></div>
        </dl>
        <p v-if="detail.sla && detail.sla.sla" class="mt-2 text-xs text-ink-gray-5">SLA {{ detail.sla.sla }} · respond by {{ detail.sla.response_by || '—' }} · resolve by {{ detail.sla.resolution_by || '—' }}</p>
        <div class="prose mt-3 max-w-none rounded-lg border border-outline-gray-1 bg-surface-white p-4 text-sm" v-html="detail.description" />

        <section class="mt-4" aria-label="Conversation">
          <h2 class="text-sm font-medium text-ink-gray-7">Conversation</h2>
          <ul v-if="detail.comments.length" class="mt-2 space-y-2">
            <li v-for="c in detail.comments" :key="c.name" class="rounded-lg border border-outline-gray-1 bg-surface-white p-3 text-sm">
              <p class="text-xs text-ink-gray-5">{{ c.commented_by || c.owner }} · {{ c.creation }}</p>
              <div class="prose mt-1 max-w-none" v-html="c.content" />
            </li>
          </ul>
          <p v-else class="mt-2 text-sm text-ink-gray-5">No replies yet.</p>
        </section>

        <form class="mt-4 rounded-lg border border-outline-gray-1 bg-surface-white p-4" @submit.prevent="send">
          <label for="ticket-reply" class="mb-1 block text-sm font-medium">Add a reply</label>
          <Textarea id="ticket-reply" v-model="reply" :rows="4" class="w-full" />
          <div class="mt-2 flex justify-end">
            <Button type="submit" variant="solid" theme="blue" :loading="busy" :disabled="!reply.trim()">Send reply</Button>
          </div>
        </form>
      </template>
    </AsyncState>
  </AppShell>
</template>
