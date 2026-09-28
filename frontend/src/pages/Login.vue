<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { Button, ErrorMessage, TextInput } from 'frappe-ui'
import { isAuthFailure } from '../api'
import { login } from '../auth'

const router = useRouter()
const email = ref('')
const password = ref('')
const loading = ref(false)
const error = ref<string | null>(null)

async function submit() {
  error.value = null
  if (!email.value || !password.value) {
    error.value = 'Enter your email and password.'
    return
  }
  loading.value = true
  try {
    await login(email.value.trim(), password.value)
    router.push((router.currentRoute.value.query.redirect as string) || '/')
  } catch (e) {
    error.value = isAuthFailure(e)
      ? 'Invalid email or password.'
      : (e as Error).message || 'Login failed. Try again.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="mx-auto w-full max-w-md px-4 py-12">
    <h1 class="text-2xl font-semibold text-ink-gray-9">Log in to BeaverBill</h1>
    <p class="mt-1 text-sm text-ink-gray-5">Manage your hosting, billing, and support in one place.</p>
    <form class="mt-6 space-y-4" @submit.prevent="submit" novalidate>
      <div>
        <label for="login-email" class="mb-1 block text-sm font-medium text-ink-gray-7">Email</label>
        <TextInput id="login-email" v-model="email" type="email" autocomplete="username" required placeholder="you@example.com" class="w-full" />
      </div>
      <div>
        <label for="login-password" class="mb-1 block text-sm font-medium text-ink-gray-7">Password</label>
        <TextInput id="login-password" v-model="password" type="password" autocomplete="current-password" required class="w-full" />
      </div>
      <ErrorMessage v-if="error" :message="error" />
      <Button type="submit" variant="solid" theme="blue" class="w-full" :loading="loading">Log in</Button>
    </form>
    <div class="mt-4 flex items-center justify-between text-sm">
      <RouterLink to="/signup" class="text-ink-blue-3 hover:underline">Create an account</RouterLink>
      <RouterLink to="/forgot-password" class="text-ink-blue-3 hover:underline">Forgot password?</RouterLink>
    </div>
  </div>
</template>
