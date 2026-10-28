<script setup lang="ts">
import { useMemoryFormGuard } from "../composables/useMemoryFormGuard";
import { computed, onScopeDispose, ref, watch } from 'vue';
import { RouterLink, useRouter } from 'vue-router';
import LoginPage from './LoginPage.vue';
import AdminRail from '../components/AdminRail.vue';
import ProjectRail from '../components/ProjectRail.vue';
import { useAuth } from '../authContext';
import { api } from '../../../src/lib/api';
import { getSession } from '../../../src/lib/token';
import { formatApiError } from '../../../src/lib/apiError';
import { roleLabel, tierLabel } from '../../../src/lib/labels';
import { isValidNewPassword, NEW_PASSWORD_VALIDATION_MESSAGE } from '../../../src/lib/passwordPolicy';
import type { Project } from '../../../src/types';
import shell from '../../../src/pages/SettingsPage.module.css';
import styles from '../../../src/pages/AccountPage.module.css';
const { session, status, changePassword, endSession } = useAuth();
const router = useRouter();
const projects = ref<Project[]>([]);
const currentPassword = ref(''), newPassword = ref(''), confirmPassword = ref(''), error = ref<string | null>(null), busy = ref(false);
const isAdmin = computed(() => status.value === 'authenticated' && session.value?.role === 'admin' && session.value.roleVerified === true);
const guest = computed(() => status.value !== 'authenticated' || session.value?.isGuest === true);
const mfaEnabled = ref<boolean | null>(null), enrolling = ref(false), mfaSecret = ref(''), mfaUri = ref(''), mfaPassword = ref(''), mfaCode = ref(''), mfaError = ref<string | null>(null), mfaBusy = ref(false);
let generation = 0;
useMemoryFormGuard(() => !guest.value && Boolean(currentPassword.value || newPassword.value || confirmPassword.value || mfaPassword.value || mfaCode.value || enrolling.value), { recovering: () => guest.value });
const mfaStatusError = ref<string | null>(null), mfaStatusLoading = ref(false);
let mfaStatusVersion = 0;
function clearSecrets() { currentPassword.value = ''; newPassword.value = ''; confirmPassword.value = ''; mfaSecret.value = ''; mfaUri.value = ''; mfaPassword.value = ''; mfaCode.value = ''; enrolling.value = false; }
// Clear sensitive state only when ownership or verified access changes.
watch([() => session.value?.userId, isAdmin, status], async () => {
    const id = ++generation;
    clearSecrets();
    mfaEnabled.value = null;
    mfaStatusError.value = null;
    mfaError.value = null;
    error.value = null;
    busy.value = false;
    mfaBusy.value = false;
    projects.value = [];
    if (!guest.value && !isAdmin.value) {
        try {
            const result = await api.listProjects();
            if (id === generation)
                projects.value = result;
        }
        catch { /* Navigation remains available. */ }
    }
}, { immediate: true, flush: 'sync' });
// Token renewal refreshes server status without discarding an enrollment or form.
async function loadMfaStatus() {
    const request = ++mfaStatusVersion;
    const ownerGeneration = generation;
    mfaStatusError.value = null;
    mfaStatusLoading.value = false;
    if (!isAdmin.value || !session.value)
        return;
    mfaStatusLoading.value = true;
    try {
        const result = await api.mfaStatus(session.value.token);
        if (request === mfaStatusVersion && ownerGeneration === generation && !enrolling.value)
            mfaEnabled.value = result.enabled;
    }
    catch (err) {
        if (request === mfaStatusVersion && ownerGeneration === generation && !enrolling.value)
            mfaStatusError.value = formatApiError(err, '两步验证状态加载失败');
    } finally {
        if (request === mfaStatusVersion && ownerGeneration === generation) mfaStatusLoading.value = false;
    }
}
watch([() => session.value?.token, isAdmin], () => { void loadMfaStatus(); }, { immediate: true });
onScopeDispose(() => { generation++; mfaStatusVersion++; clearSecrets(); });
async function submit() {
    if (busy.value)
        return;
    if (!isValidNewPassword(newPassword.value)) {
        error.value = `新${NEW_PASSWORD_VALIDATION_MESSAGE}`;
        return;
    }
    if (newPassword.value !== confirmPassword.value) {
        error.value = '两次输入的新密码不一致';
        return;
    }
    if (!currentPassword.value) {
        error.value = '请输入当前密码';
        return;
    }
    const id = generation;
    const token = session.value?.token;
    busy.value = true;
    error.value = null;
    try {
        await changePassword(currentPassword.value, newPassword.value);
        if (id !== generation && session.value)
            return;
        if (!session.value && token) {
            clearSecrets();
            await router.replace('/login');
        }
    }
    catch (err) {
        if (id === generation)
            error.value = formatApiError(err, '密码修改失败');
    }
    finally {
        if (id === generation)
            busy.value = false;
    }
}
function stillCurrent(id: number, ownerId: string) {
    if (id !== generation || session.value?.userId !== ownerId || !isAdmin.value)
        return false;
    // A storage event can be queued behind the response; inspect its owner too.
    try {
        const stored = getSession();
        return !stored || (stored.userId === ownerId && stored.role === 'admin' && stored.roleVerified === true);
    }
    catch {
        return false;
    }
}
async function mfaAction(action: 'enroll' | 'confirm' | 'disable') {
    if (!session.value || !isAdmin.value || mfaBusy.value)
        return;
    const token = session.value.token, ownerId = session.value.userId, id = generation, code = mfaCode.value.trim();
    if (action === 'enroll' && !mfaPassword.value) {
        mfaError.value = '请输入当前密码';
        return;
    }
    if (action !== 'enroll' && !/^\d{6}$/.test(code)) {
        mfaError.value = '请输入 6 位验证码';
        return;
    }
    mfaBusy.value = true;
    mfaError.value = null;
    try {
        if (action === 'enroll') {
            const resp = await api.mfaEnroll(mfaPassword.value, token);
            if (!stillCurrent(id, ownerId))
                return;
            mfaSecret.value = resp.secret;
            mfaUri.value = resp.otpauth_uri;
            mfaPassword.value = '';
            mfaCode.value = '';
            enrolling.value = true;
        }
        else {
            if (action === 'confirm')
                await api.mfaConfirm(code, token);
            else
                await api.mfaDisable(code, token);
            if (!stillCurrent(id, ownerId))
                return;
            clearSecrets();
            endSession(action === 'confirm' ? '两步验证已开启，本次登录已失效，请用验证码重新登录。' : '两步验证已关闭，本次登录已失效，请重新登录。');
            await router.replace('/login');
        }
    }
    catch (err) {
        if (stillCurrent(id, ownerId))
            mfaError.value = formatApiError(err, action === 'disable' ? '关闭两步验证失败' : '开启两步验证失败');
    }
    finally {
        if (id === generation)
            mfaBusy.value = false;
    }
}
</script>
<template>
 <div :class="[shell.wrap, guest && 'guest-account']">
<AdminRail v-if="isAdmin" /><ProjectRail v-else :projects="projects" />
 <main :class="shell.main">
<div :class="[shell.inner, guest && 'guest-account-inner']">
<section v-if="guest" class="panel guest-registration" data-guest-exempt aria-labelledby="guest-register-title">
<h1 id="guest-register-title">注册账号</h1>
<p :class="shell.hint">{{ session?.isGuest ? '设置登录信息，保留当前作品、对话与设置。' : '创建账号，开始写作并保存作品。' }}</p>
<LoginPage v-if="session?.isGuest" upgrade />
<RouterLink v-else to="/login?mode=register" class="btn btn-primary">注册账号</RouterLink>
<div class="guest-login"><RouterLink to="/login">登录已有账号</RouterLink><p v-if="session?.isGuest" :class="shell.hint">游客作品不会合并到已有账号。</p></div>
</section>
<template v-else>
<header :class="shell.header"><div><h1>账号</h1><p :class="shell.hint">查看当前账号并更新登录密码。</p></div></header>
 <div :class="styles.grid">
  <section :class="['panel',styles.card]" aria-labelledby="current-account"><h2 id="current-account">当前账号</h2><dl :class="styles.account"><div><dt>用户名</dt><dd>{{ guest?'未登录':session?.isGuest?'游客体验':session?.username }}</dd></div><div><dt>账号级别</dt><dd>{{ guest?'—':tierLabel(session?.tier??'normal') }}</dd></div><div><dt>账号角色</dt><dd>{{ guest?'—':roleLabel(session?.role??'user') }}</dd></div></dl></section>
  <section :class="['panel',styles.card]" aria-labelledby="change-password">
<h2 id="change-password">修改密码</h2><p :class="shell.hint">修改成功后，该账号在所有浏览器中的登录都会失效，需要重新登录。</p><form :class="styles.form" @submit.prevent="submit">
   <label :class="styles.field"><span>当前密码</span><input v-model="currentPassword" class="input" type="password" autocomplete="current-password" /></label>
   <label :class="styles.field"><span>新密码</span><input v-model="newPassword" class="input" type="password" autocomplete="new-password" /></label>
   <label :class="styles.field"><span>确认新密码</span><input v-model="confirmPassword" class="input" type="password" autocomplete="new-password" /></label>
   <div v-if="error" class="banner banner-error" role="alert">{{ error }}</div><button type="submit" class="btn btn-primary" :disabled="busy">{{ busy?'修改中…':'修改密码' }}</button>
  </form>
</section>
  <section v-if="isAdmin" :class="['panel',styles.card,styles.wide]" aria-labelledby="admin-console"><h2 id="admin-console">管理后台</h2><p :class="shell.hint">查看全部作品的运行记录、成本与配额，管理账号与邀请码。</p><div><RouterLink class="btn btn-secondary" to="/admin">打开管理后台</RouterLink></div></section>
  <section v-if="isAdmin" :class="['panel',styles.card,styles.wide]" aria-labelledby="mfa">
<h2 id="mfa">两步验证</h2>
   <p v-if="mfaStatusLoading" role="status">正在加载两步验证状态…</p>
   <div v-if="mfaStatusError" class="banner banner-error" role="alert">{{ mfaStatusError }} <button type="button" class="btn btn-secondary" @click="loadMfaStatus">重试两步验证状态</button></div>
   <form v-if="enrolling || mfaEnabled !== null" :class="styles.form" @submit.prevent="mfaAction(enrolling?'confirm':mfaEnabled?'disable':'enroll')">
    <template v-if="enrolling"><div :class="styles.field"><span>密钥</span><code :class="styles.secret">{{ mfaSecret }}</code></div><div :class="styles.field"><span>otpauth 链接</span><code :class="styles.secret">{{ mfaUri }}</code></div></template>
    <div v-if="mfaEnabled" class="badge badge-success">已开启</div>
    <label v-if="!enrolling && !mfaEnabled" :class="styles.field"><span>账号密码</span><input v-model="mfaPassword" class="input" type="password" autocomplete="current-password" /></label>
    <label v-else :class="styles.field"><span>验证码</span><input v-model="mfaCode" class="input" inputmode="numeric" autocomplete="one-time-code" maxlength="6" :spellcheck="false" /></label>
    <div v-if="mfaError" class="banner banner-error" role="alert">{{ mfaError }}</div><button class="btn btn-primary" type="submit" :disabled="mfaBusy">{{ enrolling?(mfaBusy?'确认中…':'确认开启'):mfaEnabled?(mfaBusy?'关闭中…':'关闭两步验证'):(mfaBusy?'生成中…':'开启两步验证') }}</button>
   </form>
  </section>
  <section :class="['panel',styles.card,styles.wide]" aria-labelledby="password-help"><h2 id="password-help">忘记密码</h2><p :class="shell.hint">本地部署不提供邮件找回。请联系本机管理员，通过 Myink 管理命令为账号重设密码。</p></section>
 </div>
</template>
</div>
</main>
</div>
</template>

<style scoped>
.guest-account { min-width: 0; }
.guest-account-inner { max-width: 560px; margin: 0 auto; padding: 46px 24px; }
.guest-registration { display: flex; flex-direction: column; gap: var(--space-4); padding: 28px; }
.guest-registration h1 { margin: 0; font-size: var(--text-title); }
.guest-login { display: flex; flex-direction: column; gap: var(--space-2); font-size: var(--text-small); }
@media (max-width: 640px) {
  .guest-account-inner { padding: 24px 16px; }
  .guest-registration { padding: 20px; }
}
</style>
