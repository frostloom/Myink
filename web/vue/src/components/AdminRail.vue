<script setup lang="ts">
import { computed, inject, nextTick, ref, watch } from 'vue';
import { persistentRailKey } from '../navigationContext';
import { RouterLink, useRoute } from 'vue-router';
import { useAuth } from '../authContext';
import styles from '../../../src/components/AdminRail.module.css';
import AdminNavIcon from './AdminNavIcon.vue';
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
const menuOpen = ref(false);
const menuButton = ref<HTMLButtonElement | null>(null);
async function closeMenu() { menuOpen.value = false; await nextTick(); menuButton.value?.focus(); }
type NavItem = { label: string; icon: string; to: string; tab?: string };
const view = (tab: string, label: string, icon = tab): NavItem => ({ tab, label, icon, to: tab === 'overview' ? '/admin' : `/admin?tab=${tab}` });
const groups: Array<{ title: string; items: NavItem[] }> = [
    { title: '运营概览', items: [view('overview', '运营概览'), view('analytics', '数据分析'), view('projects', '作品'), view('tasks', '任务'), view('runs', '全部运行'), view('logs', '访问日志')] },
    { title: '用户与会员', items: [view('users', '用户与会员'), view('invites', '邀请码'), view('feedback', '用户反馈')] },
    { title: '模型与策略', items: [{ label: 'AI 模型', icon: 'models', to: '/admin/models' }, { label: '模型分配', icon: 'routes', to: '/admin/model-routes' }, { label: '用户默认设置', icon: 'defaults', to: '/admin/defaults' }] },
    { title: '受控迭代', items: [{ label: 'Pi 管理', icon: 'runs', to: '/admin/pi' }] },
    { title: '写作资源', items: [{ label: '写作资源', icon: 'resources', to: '/admin/writing-resources' }] },
];
function selected(item: NavItem) {
    if (item.tab) return (route.path === '/admin' || !!detailView.value) && current.value === item.tab;
    if (item.to === '/admin/writing-resources') return ['/admin/writing-resources', '/admin/prompts', '/admin/genres'].includes(route.path);
    return route.path === item.to;
}
const location = computed(() => groups.flatMap(group => group.items).find(selected)?.label ?? '平台管理');
watch(() => route.fullPath, () => { menuOpen.value = false; });
async function leave() { await (props.onLogout ? props.onLogout() : logout()); }
</script>
<template>
  <aside v-if="persistent || !managed" v-show="visible !== false" :class="styles.rail" @keydown.esc="closeMenu">
    <div :class="styles.railHead"><RouterLink v-slot="{ href, navigate }" to="/admin" custom><a :class="styles.brand" :href="href" @click="navigate">Myink <small>平台管理</small></a></RouterLink><span :class="styles.mobileLocation">{{ location }}</span><button ref="menuButton" :class="styles.menuToggle" aria-label="切换后台导航" :aria-expanded="menuOpen" aria-controls="admin-navigation" @click="menuOpen = !menuOpen"><AdminNavIcon name="menu" /></button></div>
    <div id="admin-navigation" :class="styles.navigation" :data-open="menuOpen" :role="administrator ? 'navigation' : undefined" :aria-label="administrator ? '平台管理导航' : undefined">
      <template v-if="administrator"><nav v-for="group in groups" :key="group.title" :aria-label="group.title"><h2 :class="styles.groupTitle">{{ group.title }}</h2><RouterLink v-for="item in group.items" :key="item.to" v-slot="{ href, navigate }" :to="item.to" custom><a :href="href" :aria-current="selected(item) ? 'page' : undefined" @click="navigate"><AdminNavIcon :name="item.icon" /><span>{{ item.label }}</span></a></RouterLink></nav></template>
      <nav aria-label="管理账号" :class="styles.account"><RouterLink to="/account"><AdminNavIcon name="account" /><span>账号与安全</span></RouterLink><RouterLink v-if="!authenticated" to="/login">登录</RouterLink><button v-else @click="leave"><AdminNavIcon name="logout" /><span>退出登录</span></button></nav>
    </div>
  </aside>
</template>
