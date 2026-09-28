<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { Button, Dialog, ErrorMessage, TextInput, Textarea, toast } from 'frappe-ui'
import { api } from '../api'
import AppShell from '../components/AppShell.vue'
import AsyncState from '../components/AsyncState.vue'
import StatusBadge from '../components/StatusBadge.vue'

interface Ticket {
  name: string
  subject: string
  status: string
  priority?: string
  modified: string
}

const loading = ref(true)
const error = ref<string | null>(null)
const tickets = ref<Ticket[]>([])
const showNew = ref(false)
const busy = ref(false)
const formError = ref<string | null>(null)
const form = ref({ subject: '', description: '' })

async function load() {
  loading.value = true
  error.value = null
  try {
    const res = await api<{ tickets: Ticket[] }>('support.my_tickets')
    tickets.value = res.tickets
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function create() {
  formError.value = null
  if (!form.value.subject.trim() || !form.value.description.trim()) {
    formError.value = 'Subject and description are required.'
    return
  }
  busy.value = true
  try {
    const res = await api<{ ticket: string }>('support.create_ticket', { ...form.value })
    toast.success('Ticket opened')
    showNew.value = false
    form.value = { subject: '', description: '' }
    await load()
    void res
  } catch (e) {
    formError.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <AppShell>
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-semibold text-ink-gray-9">Support tickets</h1>
      <Button variant="solid" theme="blue" @click="showNew = true">New ticket</Button>
    </div>
    <AsyncState
      :loading="loading" :error="error" :empty="!loading && !error && tickets.length === 0"
      empty-title="No tickets" empty-text="Questions or issues? Open your first ticket." @retry="load"
    >
      <template #empty-action><Button variant="solid" theme="blue" @click="showNew = true">New ticket</Button></template>
      <ul class="mt-4 divide-y rounded-lg border border-outline-gray-1 bg-surface-white" aria-label="Tickets">
        <li v-for="t in tickets" :key="t.name" class="flex flex-wrap items-center justify-between gap-2 p-4">
          <div>
            <RouterLink :to="`/tickets/${t.name}`" class="font-medium text-ink-blue-3 hover:underline">{{ t.subject }}</RouterLink>
            <p class="font-mono text-xs text-ink-gray-5">{{ t.name }} · updated {{ t.modified }}</p>
          </div>
          <StatusBadge :status="t.status" />
        </li>
      </ul>
    </AsyncState>

    <Dialog v-model="showNew" title="New support ticket">
      <div class="space-y-3 text-sm">
        <div>
          <label for="tk-subject" class="mb-1 block font-medium">Subject</label>
          <TextInput id="tk-subject" v-model="form.subject" maxlength="200" class="w-full" />
        </div>
        <div>
          <label for="tk-desc" class="mb-1 block font-medium">Description</label>
          <Textarea id="tk-desc" v-model="form.description" :rows="5" class="w-full" placeholder="What is happening? Include error messages and when it started." />
        </div>
        <ErrorMessage v-if="formError" :message="formError" />
      </div>
      <template #actions>
        <Button @click="showNew = false">Cancel</Button>
        <Button variant="solid" theme="blue" :loading="busy" @click="create">Open ticket</Button>
      </template>
    </Dialog>
  </AppShell>
</template>
