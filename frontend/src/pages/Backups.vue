<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Button, toast } from 'frappe-ui'
import { api } from '../api'
import AppShell from '../components/AppShell.vue'
import AsyncState from '../components/AsyncState.vue'
import StatusBadge from '../components/StatusBadge.vue'

interface Backup {
  name: string
  service: string
  status: string
  started_at?: string
  finished_at?: string
  size_mb?: number
  retain_until?: string
}
interface Restore {
  name?: string
  restore?: string
  status: string
  backup: string
  service: string
}

const loading = ref(true)
const error = ref<string | null>(null)
const backups = ref<Backup[]>([])
const restores = ref<Restore[]>([])
const usageRows = ref<Array<{ measured_at: string; used_gb: number; quota_gb: number; overage_gb: number }>>([])
const busy = ref<string | null>(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    const b = await api<{ backups: Backup[] }>('assets.my_backups')
    backups.value = b.backups
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function requestRestore(backup: Backup) {
  busy.value = backup.name
  try {
    const res = await api<{ restore: string; status: string }>('assets.request_restore', {
      backup: backup.name,
      service: backup.service,
    })
    restores.value.unshift({ restore: res.restore, status: res.status, backup: backup.name, service: backup.service })
    toast.success('Restore requested — staff approval is required before it runs')
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    busy.value = null
  }
}

async function refreshRestore(name: string) {
  try {
    const res = await api<Restore>('assets.restore_status', { restore: name })
    const i = restores.value.findIndex((r) => (r.restore || r.name) === name)
    if (i >= 0) restores.value[i] = { ...restores.value[i], ...res }
  } catch (e) {
    toast.error((e as Error).message)
  }
}

onMounted(load)
</script>

<template>
  <AppShell>
    <h1 class="text-xl font-semibold text-ink-gray-9">Backups &amp; storage</h1>
    <p class="mt-0.5 text-sm text-ink-gray-5">Backups run on your service policy. Restores need staff approval.</p>
    <AsyncState
      :loading="loading" :error="error" :empty="!loading && !error && backups.length === 0"
      empty-title="No backups yet" empty-text="Backups appear here once your policy runs." @retry="load"
    >
      <ul class="mt-4 space-y-2" aria-label="Backups">
        <li v-for="b in backups" :key="b.name" class="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-outline-gray-1 bg-surface-white p-4">
          <div>
            <p class="font-medium">{{ b.service }}</p>
            <p class="font-mono text-xs text-ink-gray-5">
              {{ b.name }} · {{ b.size_mb ? `${b.size_mb} MB` : 'size pending' }} · retain until {{ b.retain_until || '—' }}
            </p>
          </div>
          <div class="flex items-center gap-2">
            <StatusBadge :status="b.status" />
            <Button v-if="b.status === 'Completed'" size="sm" :loading="busy === b.name" @click="requestRestore(b)">
              Request restore
            </Button>
          </div>
        </li>
      </ul>

      <section v-if="restores.length" class="mt-6" aria-label="Restore requests">
        <h2 class="text-base font-medium">Restore requests</h2>
        <ul class="mt-2 divide-y rounded-lg border border-outline-gray-1 bg-surface-white">
          <li v-for="r in restores" :key="r.restore || r.name" class="flex flex-wrap items-center justify-between gap-2 p-3 text-sm">
            <span>{{ r.service }} <span class="font-mono text-xs text-ink-gray-5">{{ r.restore || r.name }}</span></span>
            <span class="flex items-center gap-2">
              <StatusBadge :status="r.status" />
              <Button size="sm" variant="ghost" @click="refreshRestore(r.restore || r.name || '')">Refresh</Button>
            </span>
          </li>
        </ul>
      </section>

      <section v-if="usageRows.length" class="mt-6" aria-label="Storage usage">
        <h2 class="text-base font-medium">Storage usage</h2>
        <ul class="mt-2 divide-y rounded-lg border border-outline-gray-1 bg-surface-white text-sm">
          <li v-for="(u, i) in usageRows.slice(0, 10)" :key="i" class="flex justify-between p-3">
            <span>{{ u.measured_at }}</span>
            <span>{{ u.used_gb }} / {{ u.quota_gb }} GB{{ u.overage_gb > 0 ? ` (+${u.overage_gb} over)` : '' }}</span>
          </li>
        </ul>
      </section>
    </AsyncState>
  </AppShell>
</template>
