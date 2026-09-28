<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button } from 'frappe-ui'
import AsyncState from '../components/AsyncState.vue'
import { verifyEmail } from '../auth'

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const error = ref<string | null>(null)
const done = ref(false)

onMounted(async () => {
  const token = route.query.token as string
  if (!token) {
    loading.value = false
    error.value = 'This verification link is missing its token. Check your email for the full link.'
    return
  }
  try {
    await verifyEmail(token)
    done.value = true
  } catch (e) {
    error.value = (e as Error).message || 'Verification failed.'
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="mx-auto w-full max-w-md px-4 py-12">
    <h1 class="text-2xl font-semibold text-ink-gray-9">Verify your email</h1>
    <div class="mt-6">
      <AsyncState
        :loading="loading"
        :error="error"
        :empty="!loading && !error && done"
        loading-text="Verifying…"
        empty-title="Email verified"
        empty-text="Your email is confirmed. Welcome to BeaverBill."
        @retry="router.go(0)"
      >
        <template #empty-action>
          <Button variant="solid" theme="blue" @click="router.push('/')">Go to dashboard</Button>
        </template>
      </AsyncState>
    </div>
  </div>
</template>
