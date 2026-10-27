<script setup lang="ts">
import { computed, inject } from 'vue';
import { persistentRailKey } from '../navigationContext';
import { RouterLink, useRoute } from 'vue-router';
import { useAuth } from '../authContext';
import styles from '../../../src/components/AdminRail.module.css';
const props = withDefaults(defineProps<{
    persistent?: boolean;
    visible?: boolean;
    onLogout?: () => void | Promise<void>;
}>(), { visible: true, onLogout: undefined });
const managed = inject(persistentRailKey, false);
const { logout, status, session } = useAuth();
const authenticated = computed(() => status.value === 'authenticated');
const administrator = computed(() => authenticated.value && session.value?.role === 'admin' && session.value.roleVerified === true);
const route = useRoute();
const detailView = computed(() => route.path.match(/^\/admin\/(tasks|runs|users|projects)\//)?.[1]);
const current = computed(() => detailView.value ?? route.query.tab ?? 'overview');
const views = [['overview', '运营概览'], ['analytics', '数据分析'], ['users', '用户'], ['projects', '作品'], ['tasks', '任务'], ['runs', '全部运行'], ['logs', '访问日志'], ['invites', '邀请码'], ['feedback', '反馈']];
const resources = [['models', 'AI 模型'], ['model-routes', '模型分配'], ['writing-resources', '写作资源'], ['defaults', '用户默认设置']];
async function leave() { await (props.onLogout ? props.onLogout() : logout()); }
</script>
<template>
  <aside v-if="persistent || !managed" v-show="visible !== false" :class="styles.rail">
    <div :class="styles.railHead"><RouterLink :class="styles.brand" to="/admin">Myink <small>平台管理</small></RouterLink></div>
    <div id="admin-navigation" :class="styles.navigation">
      <nav v-if="administrator" aria-label="平台管理导航"><span :class="styles.groupTitle">运营管理</span><RouterLink v-for="[id,label] in views" :key="id" v-slot="{href,navigate}" :to="id === 'overview' ? '/admin' : `/admin?tab=${id}`" custom><a :href="href" :aria-current="(route.path === '/admin' || detailView) && current === id ? 'page' : undefined" @click="navigate">{{ label }}</a></RouterLink></nav>
      <nav v-if="administrator" aria-label="AI 资源管理"><span :class="styles.groupTitle">AI 资源管理</span><RouterLink v-for="[path,label] in resources" :key="path" :to="`/admin/${path}`">{{ label }}</RouterLink></nav>
      <nav aria-label="管理账号"><RouterLink to="/account">账号与安全</RouterLink><RouterLink v-if="!authenticated" to="/login">登录</RouterLink><button v-else class="btn btn-quiet" @click="leave">退出登录</button></nav>
    </div>
  </aside>
</template>
