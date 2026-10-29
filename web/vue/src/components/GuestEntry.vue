<script setup lang="ts">
import { ref } from 'vue'
import { useAuth } from '../authContext'
import { formatApiError } from '../../../src/lib/apiError'
const auth = useAuth()
const emit = defineEmits<{ entered: [] }>()
const busy = ref(false)
const error = ref<string | null>(null)
async function enter() {
  if (busy.value) return
  busy.value = true
  error.value = null
  try { if ((await auth.startGuest())?.status === 'authenticated') emit('entered') }
  catch (err) { error.value = formatApiError(err, '游客体验暂时无法进入，请重试') }
  finally { busy.value = false }
}
</script>
<template>
  <div class="guest-entry">
    <div v-if="error" role="alert" class="banner banner-error">{{ error }}</div>
    <button type="button" class="btn btn-secondary" :disabled="busy" @click="enter">{{ busy ? '正在进入…' : '游客体验' }}</button>
  </div>
</template>
<style scoped>
.guest-entry { display: flex; flex-direction: column; gap: var(--space-3); }
p { margin: 0; color: var(--ink-muted); font-size: var(--text-small); line-height: 1.6; }
</style>
