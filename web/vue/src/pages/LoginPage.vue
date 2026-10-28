<script setup lang="ts">
import GuestEntry from '../components/GuestEntry.vue'
import { useMemoryFormGuard } from "../composables/useMemoryFormGuard";
import { onScopeDispose, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuth } from '../authContext'
import { ApiError } from '../../../src/lib/api'
import { formatApiError } from '../../../src/lib/apiError'
import { isValidNewPassword, NEW_PASSWORD_VALIDATION_MESSAGE } from '../../../src/lib/passwordPolicy'
import styles from '../../../src/pages/LoginPage.module.css'

const props = defineProps<{ upgrade?: boolean }>()
const emit = defineEmits<{ upgraded: [] }>()
const auth = useAuth()
const { notice } = auth
const router = useRouter()
const route = useRoute()
const mode = ref<'login' | 'register'>(props.upgrade || route.query.mode === 'register' ? 'register' : 'login')
const username = ref('')
const password = ref('')
const confirmPassword = ref('')
const invitationCode = ref('')
const error = ref<string | null>(null)
const busy = ref(false)
const mfaToken = ref<string | null>(null)
const code = ref('')
const { permitNavigation } = useMemoryFormGuard(() => auth.status.value !== 'authenticated' && Boolean(username.value || password.value || confirmPassword.value || invitationCode.value || code.value || mfaToken.value), { recovering: () => auth.status.value === 'anonymous' })
watch(() => auth.session.value?.userId, (current, previous) => {
  if (current !== previous && mfaToken.value) {
    mfaToken.value = null
    code.value = ''
    error.value = null
  }
})
let alive = true
onScopeDispose(() => { alive = false })
function switchMode(next: 'login' | 'register') {
  if (busy.value) return
  mode.value = next
  password.value = confirmPassword.value = invitationCode.value = ''
  error.value = null
}
function back() {
  if (busy.value) return
  mfaToken.value = null
  code.value = ''
  error.value = null
}
function failure(err: unknown, fallback: string) {
  error.value = err instanceof ApiError && err.code === 'network_error'
    ? '无法连接服务，请检查网络后重试' : formatApiError(err, fallback)
}
function goHome() {
  if (props.upgrade) { emit('upgraded'); return }
  const current = auth.session.value
  if (alive && auth.status.value === 'authenticated' && current?.roleVerified) {
    void permitNavigation(() => router.replace(current.role === 'admin' ? '/admin' : '/long'))
  }
}
async function submit() {
  if (busy.value) return
  const name = username.value.trim()
  if (!/^[A-Za-z0-9_-]{3,64}$/.test(name)) { error.value = '用户名需为 3–64 位英文字母、数字、下划线或短横线'; return }
  const length = Array.from(password.value).length
  if (mode.value === 'login' && (length < 1 || length > 128)) { error.value = '请输入有效密码（最多 128 个字符）'; return }
  if (mode.value === 'register' && !isValidNewPassword(password.value)) { error.value = NEW_PASSWORD_VALIDATION_MESSAGE; return }
  if (mode.value === 'register' && password.value !== confirmPassword.value) { error.value = '两次输入的密码不一致'; return }
  if (mode.value === 'register' && !invitationCode.value.trim()) { error.value = '请输入邀请码'; return }
  busy.value = true
  error.value = null
  try {
    const accepted = mode.value === 'login'
      ? await auth.login(name.toLowerCase(), password.value)
      : await auth.register(name.toLowerCase(), password.value, invitationCode.value.trim())
    if (!alive) return
    if (accepted?.status === 'mfa') {
      mfaToken.value = accepted.mfaToken
      password.value = confirmPassword.value = invitationCode.value = code.value = ''
    } else if (accepted?.status === 'authenticated') goHome()
  } catch (err) { if (alive) failure(err, mode.value === 'login' ? '登录失败' : '注册失败') }
  finally { busy.value = false }
}
async function submitCode() {
  if (busy.value || !mfaToken.value) return
  const trimmed = code.value.trim()
  if (!/^\d{6}$/.test(trimmed)) { error.value = '请输入 6 位验证码'; return }
  busy.value = true
  error.value = null
  try { if (await auth.completeMfa(mfaToken.value, trimmed)) goHome() }
  catch (err) { if (alive) failure(err, '验证码验证失败') }
  finally { busy.value = false }
}
</script>

<template>
  <div :class="upgrade ? 'guest-upgrade-form' : styles.wrap">
    <form v-if="mfaToken" :class="['panel', styles.card]" @submit.prevent="submitCode">
      <h1>输入验证码</h1>
      <label :class="styles.field"><span>验证码</span><input v-model="code" class="input" inputmode="numeric" autocomplete="one-time-code" maxlength="6" :spellcheck="false" autofocus /></label>
      <div v-if="error" class="banner banner-error" role="alert">{{ error }}</div>
      <button class="btn btn-primary" type="submit" :disabled="busy">{{ busy ? '验证中…' : '验证' }}</button>
      <button class="btn btn-secondary" type="button" :disabled="busy" @click="back">返回</button>
    </form>
    <form v-else :class="['panel', styles.card]" @submit.prevent="submit">
      <div v-if="!upgrade"><h1>Myink 作品工作台</h1><p :class="styles.sub">长篇网文多 Agent 创作助手</p></div>
      <div v-if="!upgrade" :class="styles.tabs" role="tablist" aria-label="账号入口">
        <button v-for="tab in (['login', 'register'] as const)" :key="tab" type="button" role="tab" :aria-selected="mode === tab" :class="mode === tab ? styles.tabActive : styles.tab" :disabled="busy" @click="switchMode(tab)">{{ tab === 'login' ? '登录' : '注册账号' }}</button>
      </div>
      <label :class="styles.field"><span>用户名</span><input v-model="username" class="input" autocomplete="username" autocapitalize="none" :spellcheck="false" autofocus /></label>
      <label :class="styles.field"><span>密码</span><input v-model="password" class="input" type="password" :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" /></label>
      <template v-if="mode === 'register'">
        <label :class="styles.field"><span>确认密码</span><input v-model="confirmPassword" class="input" type="password" autocomplete="new-password" /></label>
        <label :class="styles.field"><span>邀请码</span><input v-model="invitationCode" class="input" autocomplete="off" autocapitalize="none" :spellcheck="false" /></label>
      </template>
      <div v-if="error" class="banner banner-error" role="alert">{{ error }}</div>
      <div v-else-if="notice" class="banner banner-warning" role="status">{{ notice }}</div>
      <button class="btn btn-primary" type="submit" :disabled="busy">{{ busy ? (mode === 'login' ? '登录中…' : '注册中…') : (mode === 'login' ? '登录' : '创建账号') }}</button>
      <GuestEntry v-if="!upgrade" v-show="auth.status.value !== 'authenticated'" @entered="goHome" />
    </form>
  </div>
</template>

<style scoped>
.guest-upgrade-form > form { width: 100%; max-width: none; border: 0; padding: 0; box-shadow: none; background: transparent; }
</style>
