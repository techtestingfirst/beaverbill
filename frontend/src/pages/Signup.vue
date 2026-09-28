<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { Button, ErrorMessage, TextInput } from 'frappe-ui'
import { login, signup } from '../auth'

const router = useRouter()
const fullName = ref('')
const email = ref('')
const password = ref('')
const loading = ref(false)
const error = ref<string | null>(null)

async function submit() {
  error.value = null
  if (password.value.length < 8) {
    error.value = 'Password must be at least 8 characters.'
    return
  }
  loading.value = true
  try {
    await signup(fullName.value.trim(), email.value.trim(), password.value)
    await login(email.value.trim(), password.value)
    router.push('/')
  } catch (e) {
    error.value = (e as Error).message || 'Signup failed. Try again.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="mx-auto w-full max-w-md px-4 py-12">
    <h1 class="text-2xl font-semibold text-ink-gray-9">Create your account</h1>
    <p class="mt-1 text-sm text-ink-gray-5">We will email you a verification link after signup.</p>
    <form class="mt-6 space-y-4" @submit.prevent="submit" novalidate>
      <div>
        <label for="signup-name" class="mb-1 block text-sm font-medium text-ink-gray-7">Full name</label>
        <TextInput id="signup-name" v-model="fullName" autocomplete="name" required class="w-full" />
      </div>
      <div>
        <label for="signup-email" class="mb-1 block text-sm font-medium text-ink-gray-7">Email</label>
        <TextInput id="signup-email" v-model="email" type="email" autocomplete="email" required class="w-full" />
      </div>
      <div>
        <label for="signup-password" class="mb-1 block text-sm font-medium text-ink-gray-7">Password</label>
        <TextInput id="signup-password" v-model="password" type="password" autocomplete="new-password" required minlength="8" class="w-full" />
        <p class="mt-1 text-xs text-ink-gray-5">At least 8 characters.</p>
      </div>
      <ErrorMessage v-if="error" :message="error" />
      <Button type="submit" variant="solid" theme="blue" class="w-full" :loading="loading">Create account</Button>
    </form>
    <p class="mt-4 text-sm text-ink-gray-5">
      Already have an account?
      <RouterLink to="/login" class="text-ink-blue-3 hover:underline">Log in</RouterLink>
    </p>
  </div>
</template>
