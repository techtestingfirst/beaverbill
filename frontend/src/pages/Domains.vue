<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Button, Dialog, ErrorMessage, Select, TextInput, toast } from 'frappe-ui'
import { api } from '../api'
import AppShell from '../components/AppShell.vue'
import AsyncState from '../components/AsyncState.vue'
import StatusBadge from '../components/StatusBadge.vue'

interface Domain {
  name: string
  domain_name: string
  status: string
  expiry_date?: string
  auto_renew?: number
  nameservers?: string[]
  transfer_status?: string
  records?: Array<{ name: string; record_type: string; host: string; value: string; ttl: number }>
}
interface Cert {
  name: string
  domain: string
  service?: string
  status: string
  expires_at?: string
}

const loading = ref(true)
const error = ref<string | null>(null)
const domains = ref<Domain[]>([])
const certs = ref<Cert[]>([])
const expanded = ref<string | null>(null)
const showDns = ref(false)
const showCert = ref(false)
const dnsForm = ref({ domain: '', record_type: 'A', host: '', value: '', ttl: 3600 })
const certForm = ref({ domain: '', service: '', validation_method: 'DNS' })
const busy = ref(false)
const formError = ref<string | null>(null)

async function load() {
  loading.value = true
  error.value = null
  try {
    const [d, c] = await Promise.all([
      api<{ domains: Domain[] }>('assets.my_domains'),
      api<{ certificates: Cert[] }>('assets.my_certificates'),
    ])
    domains.value = d.domains
    certs.value = c.certificates
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function toggle(domain: string) {
  if (expanded.value === domain) {
    expanded.value = null
    return
  }
  try {
    const res = await api<Domain>('assets.domain_detail', { domain })
    const i = domains.value.findIndex((d) => d.name === domain)
    if (i >= 0) domains.value[i] = { ...domains.value[i], ...res }
    expanded.value = domain
  } catch (e) {
    toast.error((e as Error).message)
  }
}

function openDns(domain: string) {
  dnsForm.value = { domain, record_type: 'A', host: '', value: '', ttl: 3600 }
  formError.value = null
  showDns.value = true
}

async function addDns() {
  busy.value = true
  formError.value = null
  try {
    await api('assets.dns_add', { ...dnsForm.value })
    toast.success('DNS record added')
    showDns.value = false
    expanded.value = null
    await load()
  } catch (e) {
    formError.value = (e as Error).message
  } finally {
    busy.value = false
  }
}

async function removeDns(domain: string, record: string) {
  try {
    await api('assets.dns_remove', { record })
    toast.success('DNS record deactivated')
    expanded.value = null
    await load()
  } catch (e) {
    toast.error((e as Error).message)
  }
}

function openCert(domain: string) {
  certForm.value = { domain, service: '', validation_method: 'DNS' }
  formError.value = null
  showCert.value = true
}

async function orderCert() {
  busy.value = true
  formError.value = null
  try {
    await api('assets.request_certificate', { ...certForm.value, service: certForm.value.service || undefined })
    toast.success('Certificate requested — complete validation to activate')
    showCert.value = false
    await load()
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
    <h1 class="text-xl font-semibold text-ink-gray-9">Domains &amp; SSL</h1>
    <AsyncState
      :loading="loading" :error="error" :empty="!loading && !error && domains.length === 0"
      empty-title="No domains yet" empty-text="Register a domain during checkout, then manage it here." @retry="load"
    >
      <ul class="mt-4 space-y-3" aria-label="Domains">
        <li v-for="d in domains" :key="d.name" class="rounded-lg border border-outline-gray-1 bg-surface-white p-4">
          <button class="flex w-full items-center justify-between gap-2 text-left" :aria-expanded="expanded === d.name" @click="toggle(d.name)">
            <span>
              <span class="font-medium">{{ d.domain_name }}</span>
              <span class="block text-xs text-ink-gray-5">Expires {{ d.expiry_date || '—' }}{{ d.auto_renew ? ' · auto-renew on' : '' }}</span>
            </span>
            <StatusBadge :status="d.status" />
          </button>
          <div v-if="expanded === d.name" class="mt-3 border-t border-outline-gray-1 pt-3 text-sm">
            <h3 class="font-medium">DNS records</h3>
            <ul v-if="d.records?.length" class="mt-1 divide-y font-mono text-xs">
              <li v-for="r in d.records" :key="r.name" class="flex items-center justify-between gap-2 py-1.5">
                <span>{{ r.record_type }} {{ r.host }} → {{ r.value }} (TTL {{ r.ttl }})</span>
                <button class="portal-danger hover:underline" :aria-label="`Remove ${r.record_type} record ${r.host}`" @click="removeDns(d.name, r.name)">Remove</button>
              </li>
            </ul>
            <p v-else class="mt-1 text-ink-gray-5">No active records.</p>
            <p class="mt-2 text-xs text-ink-gray-5">Nameservers: {{ (d.nameservers || []).join(', ') || '—' }}</p>
            <div class="mt-3 flex flex-wrap gap-2">
              <Button size="sm" @click="openDns(d.name)">Add DNS record</Button>
              <Button size="sm" @click="openCert(d.name)">Order SSL certificate</Button>
            </div>
          </div>
        </li>
      </ul>

      <section class="mt-6" aria-label="SSL certificates">
        <h2 class="text-base font-medium">SSL certificates</h2>
        <ul v-if="certs.length" class="mt-2 divide-y rounded-lg border border-outline-gray-1 bg-surface-white" aria-label="Certificates">
          <li v-for="c in certs" :key="c.name" class="flex flex-wrap items-center justify-between gap-2 p-3 text-sm">
            <span>{{ c.domain }} <span class="font-mono text-xs text-ink-gray-5">{{ c.name }}</span></span>
            <span class="flex items-center gap-2">
              <span class="text-xs text-ink-gray-5">Expires {{ c.expires_at || '—' }}</span>
              <StatusBadge :status="c.status" />
            </span>
          </li>
        </ul>
        <p v-else class="mt-2 text-sm text-ink-gray-5">No certificates yet.</p>
      </section>
    </AsyncState>

    <Dialog v-model="showDns" title="Add DNS record">
      <div class="grid grid-cols-2 gap-2 text-sm">
        <div>
          <label for="dns-type" class="mb-1 block font-medium">Type</label>
          <Select id="dns-type" v-model="dnsForm.record_type" :options="['A', 'AAAA', 'CNAME', 'MX', 'TXT', 'SRV', 'NS', 'CAA'].map((t) => ({ label: t, value: t }))" class="w-full" />
        </div>
        <div>
          <label for="dns-host" class="mb-1 block font-medium">Host</label>
          <TextInput id="dns-host" v-model="dnsForm.host" placeholder="www or @" class="w-full" />
        </div>
        <div class="col-span-2">
          <label for="dns-value" class="mb-1 block font-medium">Value</label>
          <TextInput id="dns-value" v-model="dnsForm.value" class="w-full" />
        </div>
        <div>
          <label for="dns-ttl" class="mb-1 block font-medium">TTL (seconds)</label>
          <TextInput id="dns-ttl" v-model.number="dnsForm.ttl" type="number" class="w-full" />
        </div>
      </div>
      <ErrorMessage v-if="formError" :message="formError" class="mt-2" />
      <template #actions>
        <Button @click="showDns = false">Cancel</Button>
        <Button variant="solid" theme="blue" :loading="busy" @click="addDns">Add record</Button>
      </template>
    </Dialog>

    <Dialog v-model="showCert" title="Order SSL certificate">
      <div class="space-y-2 text-sm">
        <p>We issue a validation token next. For DNS validation, publish the shown TXT record, then validation runs automatically.</p>
        <div>
          <label for="cert-method" class="mb-1 block font-medium">Validation method</label>
          <Select id="cert-method" v-model="certForm.validation_method" :options="[{ label: 'DNS', value: 'DNS' }, { label: 'HTTP', value: 'HTTP' }]" class="w-full" />
        </div>
      </div>
      <ErrorMessage v-if="formError" :message="formError" class="mt-2" />
      <template #actions>
        <Button @click="showCert = false">Cancel</Button>
        <Button variant="solid" theme="blue" :loading="busy" @click="orderCert">Order certificate</Button>
      </template>
    </Dialog>
  </AppShell>
</template>
