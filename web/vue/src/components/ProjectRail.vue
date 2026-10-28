<script setup lang="ts">
import { computed, inject, ref, watch } from 'vue';
import { persistentRailKey } from '../navigationContext';
import { RouterLink, useRoute } from 'vue-router';
import { useAuth } from '../authContext';
import { isProjectDraft } from '../../../src/lib/projectCreation';
import type { Project } from '../../../src/types';
import styles from '../../../src/components/ProjectRail.module.css';
const props = withDefaults(defineProps<{
    projects: Project[];
    persistent?: boolean;
    visible?: boolean;
    onLogout?: () => void | Promise<void>;
}>(), { visible: true, onLogout: undefined });
const managed = inject(persistentRailKey, false);
const { session, status, logout } = useAuth();
const route = useRoute();
const projectId = computed(() => String(route.params.projectId ?? ''));
const inBook = computed(() => props.projects.find(p => p.id === projectId.value));
const section = ref<'long' | 'short'>('long');
watch(() => route.path.startsWith('/short') ? 'short' : route.path.startsWith('/long') ? 'long' : inBook.value ? inBook.value.form ?? 'long' : null, next => {
    if (next) section.value = next;
}, { immediate: true, flush: 'sync' });
const books = computed(() => props.projects.filter(p => !isProjectDraft(p) && (p.form ?? 'long') === section.value));
const authenticated = computed(() => status.value === 'authenticated');
const bookLinks = computed(() => inBook.value?.form === 'short' ? [] : [['lore', '设定'], ['settings', '创作设置'], ['audit', '全局审计']]);
const globalLinks = [['environment', '高级设置'], ['theme', '主题'], ['styles', '文风库'], ['writing-resources', '写作资源']];
function feedback() { window.dispatchEvent(new Event('myink:feedback')); }
async function leave() { await (props.onLogout ? props.onLogout() : logout()); }
</script>
<template>
  <aside v-if="persistent || !managed" v-show="visible !== false" :class="styles.rail" data-guest-exempt>
    <RouterLink to="/long" :class="styles.brand">Myink</RouterLink>
    <nav :class="styles.sections" aria-label="作品分区">
      <RouterLink v-for="[id,label] in [['long','长篇'],['short','短篇']]" :key="id" v-slot="{href,navigate}" :to="`/${id}`" custom>
        <a :href="href" :class="[styles.sectionItem, section === id && styles.sectionCurrent]" :aria-current="section === id ? 'true' : undefined" @click="navigate"><span :class="styles.title">{{ label }}</span></a>
      </RouterLink>
    </nav>
    <nav :class="styles.nav" aria-label="作品列表">
      <span v-if="books.length" :class="styles.groupHead" aria-hidden="true">作品</span>
      <RouterLink v-for="p in books" :key="p.id" :to="`/projects/${p.id}`" :class="styles.item" :active-class="styles.active"><span :class="styles.title">{{ p.title }}</span></RouterLink>
    </nav>
    <nav v-if="projectId && bookLinks.length" :class="styles.pageLinks" aria-label="本书页面">
      <span :class="styles.groupHead" aria-hidden="true">本书</span>
      <RouterLink v-for="[path,label] in bookLinks" :key="path" :to="`/projects/${projectId}/${path}`" :class="styles.item" :active-class="styles.active"><span :class="styles.title">{{ label }}</span></RouterLink>
    </nav>
    <div v-if="persistent" id="project-rail-resource-actions" />
    <slot v-else-if="projectId" name="resource-actions" />
    <nav v-if="!projectId" :class="styles.settings" aria-label="全局设置">
      <span :class="styles.groupHead" aria-hidden="true">全局</span>
      <RouterLink v-for="[path,label] in globalLinks" :key="path" :to="`/${path}`" :class="styles.item" :active-class="styles.active"><span :class="styles.title">{{ label }}</span></RouterLink>
    </nav>
    <button v-if="authenticated" type="button" :class="[styles.item,styles.feedbackPin]" @click="feedback"><span :class="styles.title">反馈</span></button>
    <div :class="styles.foot">
      <RouterLink v-if="authenticated && session?.role === 'admin' && session.roleVerified === true" to="/admin" :class="styles.item" :active-class="styles.active"><span :class="styles.title">管理后台</span></RouterLink>
      <RouterLink to="/account" :class="styles.item" :active-class="styles.active"><span :class="styles.title">账号</span></RouterLink>
      <div :class="styles.userRow"><span :class="styles.user">{{ authenticated ? (session?.isGuest ? '游客' : session?.username) : '未登录' }}</span><RouterLink v-if="!authenticated" to="/login" class="btn btn-quiet">登录</RouterLink><button v-else type="button" class="btn btn-quiet" @click="leave">登出</button></div>
    </div>
  </aside>
  <Teleport v-else-if="projectId && $slots['resource-actions']" to="#project-rail-resource-actions"><slot name="resource-actions" /></Teleport>
</template>
