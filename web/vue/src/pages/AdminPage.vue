<script setup lang="ts">
import { computed, provide, ref, watch } from 'vue'
import { RouterView, useRoute } from 'vue-router'
import AdminRail from '../components/AdminRail.vue'
import { useAuth } from '../authContext'
import { adminContextKey } from './admin/context'
import styles from '../../../src/pages/AdminPage.module.css'
const { session, status, revalidate, logout } = useAuth()
const route = useRoute()
const forbidden = ref(false)
const identity = computed(() => session.value?.userId ?? '')
watch(identity, () => { forbidden.value = false })
function onForbidden() { forbidden.value = true; void revalidate() }
provide(adminContextKey, { get token() { return session.value?.token ?? '' }, onForbidden })
const allowed = computed(() => status.value === 'authenticated' && session.value?.role === 'admin' && session.value.roleVerified === true)
</script>
<template>
  <div v-if="forbidden" :class="styles.denied" role="alert"><h1>管理员权限已变化</h1><p>受保护数据已清除，正在重新验证当前会话。</p></div>
  <div v-else :class="styles.wrap">
    <AdminRail :on-logout="logout" />
    <main :class="styles.main">
      <RouterView v-if="allowed" :key="`${identity}:${route.path}`" />
      <div v-else class="empty">只有管理员可以打开控制台。</div>
    </main>
  </div>
</template>
