<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { Button, Dialog, ErrorMessage, Select, Switch, TextInput, toast } from 'frappe-ui'
import { api } from '../api'
import { session } from '../auth'
import AppShell from '../components/AppShell.vue'
import AsyncState from '../components/AsyncState.vue'

interface Profile {
  name: string
  customer_name: string
  customer_type?: string
  company_name?: string
  status: string
  locale?: string
  timezone?: string
  email_verified?: number
  consent_marketing?: number
}
interface Contact {
  name: string
  contact_type: string
  full_name: string
  email: string
  phone?: string
}
interface Notice {
  name: string
  subject: string
  message?: string
  read?: number
  created_at?: string
}

const loading = ref(true)
const error = ref<string | null>(null)
const profile = ref<Profile | null>(null)
const contacts = ref<Contact[]>([])
const notices = ref<Notice[]>([])
const unread = ref(0)
const saving = ref(false)
const showContact = ref(false)
const formError = ref<string | null>(null)
const contactForm = ref({ contact_type: 'Billing', full_name: '', email: '', phone: '' })

async function load() {
  loading.value = true
  error.value = null
  try {
    const [p, c, n, u] = await Promise.all([
      api<Profile>('account.get_profile'),
      api<{ contacts: Contact[] }>('account.list_contacts'),
      api<{ notifications: Notice[] }>('support.list_notifications'),
      api<{ unread: number }>('support.unread_count'),
    ])
    profile.value = p
    contacts.value = c.contacts
    notices.value = n.notifications
    unread.value = u.unread
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

async function saveProfile() {
  if (!profile.value) return
  saving.value = true
  try {
    profile.value = await api<Profile>('account.update_profile', {
      customer_name: profile.value.customer_name,
      locale: profile.value.locale,
      timezone: profile.value.timezone,
      consent_marketing: profile.value.consent_marketing ? 1 : 0,
    })
    toast.success('Profile saved')
  } catch (e) {
    toast.error((e as Error).message)
  } finally {
    saving.value = false
  }
}

async function addContact() {
  formError.value = null
  if (!contactForm.value.full_name.trim() || !contactForm.value.email.trim()) {
    formError.value = 'Name and email are required.'
    return
  }
  try {
    await api('account.add_contact', { ...contactForm.value })
    toast.success('Contact added')
    showContact.value = false
    contactForm.value = { contact_type: 'Billing', full_name: '', email: '', phone: '' }
    contacts.value = (await api<{ contacts: Contact[] }>('account.list_contacts')).contacts
  } catch (e) {
    formError.value = (e as Error).message
  }
}

async function removeContact(name: string) {
  try {
    await api('account.delete_contact', { name })
    contacts.value = contacts.value.filter((c) => c.name !== name)
  } catch (e) {
    toast.error((e as Error).message)
  }
}

async function markRead(name: string) {
  try {
    await api('support.mark_read', { name })
    const n = notices.value.find((x) => x.name === name)
    if (n) n.read = 1
    unread.value = Math.max(0, unread.value - 1)
  } catch (e) {
    toast.error((e as Error).message)
  }
}

onMounted(load)
</script>

<template>
  <AppShell>
    <h1 class="text-xl font-semibold text-ink-gray-9">Profile</h1>
    <AsyncState :loading="loading" :error="error" @retry="load">
      <template v-if="profile">
        <section class="mt-4 rounded-lg border border-outline-gray-1 bg-surface-white p-4" aria-label="Account details">
          <h2 class="text-sm font-medium text-ink-gray-7">Account</h2>
          <dl class="mt-2 grid gap-3 text-sm sm:grid-cols-2">
            <div>
              <dt class="text-xs text-ink-gray-5">Login</dt><dd>{{ session.user }}</dd>
            </div>
            <div>
              <dt class="text-xs text-ink-gray-5">Status</dt>
              <dd>{{ profile.status }}{{ profile.email_verified ? ' · email verified' : ' · email not verified' }}</dd>
            </div>
            <div>
              <label for="profile-name" class="mb-1 block text-xs text-ink-gray-5">Display name</label>
              <TextInput id="profile-name" v-model="profile.customer_name" class="w-full" />
            </div>
            <div>
              <label for="profile-tz" class="mb-1 block text-xs text-ink-gray-5">Timezone</label>
              <TextInput id="profile-tz" v-model="profile.timezone" placeholder="Asia/Kolkata" class="w-full" />
            </div>
          </dl>
          <label class="mt-3 flex items-center gap-2 text-sm">
            <Switch :model-value="!!profile.consent_marketing" @update:model-value="profile.consent_marketing = $event ? 1 : 0" /> Product news and offers
          </label>
          <div class="mt-3">
            <Button variant="solid" theme="blue" :loading="saving" @click="saveProfile">Save profile</Button>
          </div>
        </section>

        <section class="mt-4 rounded-lg border border-outline-gray-1 bg-surface-white p-4" aria-label="Contacts">
          <div class="flex items-center justify-between">
            <h2 class="text-sm font-medium text-ink-gray-7">Contacts</h2>
            <Button size="sm" @click="showContact = true">Add contact</Button>
          </div>
          <ul v-if="contacts.length" class="mt-2 divide-y text-sm">
            <li v-for="c in contacts" :key="c.name" class="flex items-center justify-between py-2">
              <span>{{ c.full_name }} <span class="text-ink-gray-5">· {{ c.contact_type }} · {{ c.email }}</span></span>
              <Button size="sm" variant="ghost" :aria-label="`Remove ${c.full_name}`" @click="removeContact(c.name)">Remove</Button>
            </li>
          </ul>
          <p v-else class="mt-2 text-sm text-ink-gray-5">No extra contacts.</p>
        </section>

        <section id="notifications" class="mt-4 rounded-lg border border-outline-gray-1 bg-surface-white p-4" aria-label="Notifications" tabindex="-1">
          <h2 class="text-sm font-medium text-ink-gray-7">Notifications ({{ unread }} unread)</h2>
          <ul v-if="notices.length" class="mt-2 divide-y text-sm">
            <li v-for="n in notices.slice(0, 20)" :key="n.name" class="flex items-start justify-between gap-2 py-2">
              <div :class="n.read ? 'text-ink-gray-5' : ''">
                <p class="font-medium">{{ n.subject }}</p>
                <p v-if="n.message" class="mt-0.5 line-clamp-2">{{ n.message }}</p>
              </div>
              <Button v-if="!n.read" size="sm" variant="ghost" @click="markRead(n.name)">Mark read</Button>
            </li>
          </ul>
          <p v-else class="mt-2 text-sm text-ink-gray-5">No notifications.</p>
        </section>
      </template>
    </AsyncState>

    <Dialog v-model="showContact" title="Add contact">
      <div class="space-y-3 text-sm">
        <div>
          <label for="ct-type" class="mb-1 block font-medium">Type</label>
          <Select id="ct-type" v-model="contactForm.contact_type" :options="['Billing', 'Technical', 'Other'].map((t) => ({ label: t, value: t }))" class="w-full" />
        </div>
        <div>
          <label for="ct-name" class="mb-1 block font-medium">Full name</label>
          <TextInput id="ct-name" v-model="contactForm.full_name" class="w-full" />
        </div>
        <div>
          <label for="ct-email" class="mb-1 block font-medium">Email</label>
          <TextInput id="ct-email" v-model="contactForm.email" type="email" class="w-full" />
        </div>
        <ErrorMessage v-if="formError" :message="formError" />
      </div>
      <template #actions>
        <Button @click="showContact = false">Cancel</Button>
        <Button variant="solid" theme="blue" @click="addContact">Add contact</Button>
      </template>
    </Dialog>
  </AppShell>
</template>
