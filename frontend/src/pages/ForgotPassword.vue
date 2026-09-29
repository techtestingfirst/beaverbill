<script setup lang="ts">
import { ref } from 'vue'
import { Button, ErrorMessage, TextInput } from 'frappe-ui'
import { requestPasswordReset } from '../api'

const email = ref('')
const loading = ref(false)
const error = ref<string | null>(null)
const sent = ref(false)

async function submit() {
  error.value = null
  if (!email.value) {
    error.value = 'Enter your account email.'
    return
  }
  loading.value = true
  try {
    await requestPasswordReset(email.value.trim())
    sent.value = true
  } catch (e) {
    error.value = (e as Error).message || 'Could not send the reset email.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="mx-auto w-full max-w-md px-4 py-12">
    <h1 class="text-2xl font-semibold text-ink-gray-9">Reset your password</h1>
    <p class="mt-1 text-sm text-ink-gray-5">We will email you a link to choose a new password.</p>
    <div v-if="sent" role="status" class="mt-6 rounded-lg border border-outline-green-2 bg-surface-green-1 p-4 text-sm text-ink-gray-8">
      If an account exists for that email, a reset link is on its way. It expires after a short time.
    </div>
    <form v-else class="mt-6 space-y-4" @submit.prevent="submit" novalidate>
      <div>
        <label for="reset-email" class="mb-1 block text-sm font-medium text-ink-gray-7">Email</label>
        <TextInput id="reset-email" v-model="email" type="email" autocomplete="email" required class="w-full" />
      </div>
      <ErrorMessage v-if="error" :message="error" />
      <Button type="submit" variant="solid" theme="blue" class="w-full" :loading="loading">Send reset link</Button>
    </form>
    <p class="mt-4 text-sm">
      <RouterLink to="/login" class="portal-link">Back to login</RouterLink>
    </p>
  </div>
</template>
