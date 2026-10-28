<script setup lang="ts">
import { onMounted, onScopeDispose, ref, watch } from 'vue'
import { useAuth } from '../authContext'
import { api } from '../../../src/lib/api'
import NativeDialog from './NativeDialog.vue'
import LoginPage from '../pages/LoginPage.vue'
import styles from '../../../src/components/GuestPromptDialog.module.css'
const { session } = useAuth()
const open = ref(false)
const message = ref('')
let version = 0
let controller: AbortController | null = null
function close() {
  open.value = false
  version++
  controller?.abort()
}
async function update(event: Event) {
  const detail = (event as CustomEvent<{ userId?: string; exhausted?: boolean; category?: 'short' | 'long'; batch?: boolean }>).detail
  if (!session.value?.isGuest || !detail?.exhausted || !detail.userId || detail.userId !== session.value.userId) return
  controller?.abort()
  const request = new AbortController()
  controller = request
  const id = ++version
  message.value = '本次请求超出可用体验额度。注册账号获取更多写作额度，已有内容仍可编辑和导出。'
  open.value = true
  try {
    const quota = await api.guestQuota(session.value.token, request.signal)
    if (id !== version || request.signal.aborted) return
    const category = detail.category
    if (!category) return
    const other = category === 'short' ? 'long' : 'short'
    const label = category === 'short' ? '短篇' : '长篇'
    if (quota[category].remaining > 0) {
      if (detail.batch) message.value = '本次请求超出可用体验额度，请减少批次章数，或注册账号获取更多写作额度。'
      return
    }
    message.value = `${label}体验额度已用完。注册账号获取更多写作额度，已有内容仍可编辑和导出。${quota[other].remaining > 0 ? (other === 'short' ? '短篇' : '长篇') + '仍可继续创作。' : ''}`
  } catch { /* The rejection remains authoritative even when balance lookup fails. */ }
}
function upgrade() {
  if (!session.value?.isGuest) return
  message.value = '注册后保留当前作品、对话与设置。'
  open.value = true
}
watch(() => [session.value?.userId, session.value?.isGuest], close)
onMounted(() => {
  window.addEventListener('myink:guest-quota', update)
  window.addEventListener('myink:guest-upgrade', upgrade)
})
onScopeDispose(() => {
  close()
  window.removeEventListener('myink:guest-quota', update)
  window.removeEventListener('myink:guest-upgrade', upgrade)
})
</script>
<template>
  <Teleport to="body">
    <NativeDialog v-if="open && session?.isGuest" :class="[styles.dialog, 'guest-upgrade-dialog']" aria-labelledby="guest-upgrade-title" :on-close="close">
      <header :class="styles.head"><h2 id="guest-upgrade-title">注册保留作品</h2><button type="button" :class="styles.close" aria-label="关闭注册" @click="close">×</button></header>
      <div :class="styles.body"><p>{{ message }}</p><LoginPage upgrade @upgraded="close" /></div>
    </NativeDialog>
  </Teleport>
</template>
<style scoped>
.guest-upgrade-dialog { max-height: calc(100dvh - 32px); overflow-y: auto; }
</style>
