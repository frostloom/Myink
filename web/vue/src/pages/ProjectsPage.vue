<script setup lang="ts">
import { computed, inject, onMounted, onScopeDispose, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { authKey } from '../authContext'
import ProjectRail from '../components/ProjectRail.vue'
import { api, ApiError } from '../../../src/lib/api'
import { formatApiError } from '../../../src/lib/apiError'
import { isProjectDraft, projectHref } from '../../../src/lib/projectCreation'
import type { Project } from '../../../src/types'
import styles from '../../../src/pages/ProjectsPage.module.css'
import rail from '../../../src/components/ProjectRail.module.css'

const auth = inject(authKey, null)
const props = withDefaults(defineProps<{ form?: 'long' | 'short'; username: string; guest?: boolean }>(), { form: 'long' })
defineEmits<{ logout: [] }>()
const projects = ref<Project[] | null>(null)
const error = ref<string | null>(null)
const deleteError = ref<string | null>(null)
const deleting = ref(new Set<string>())
let alive = true
let loadId = 0
const label = computed(() => props.form === 'short' ? '短篇' : '长篇')
const mine = computed(() => (projects.value ?? []).filter(p => (p.form ?? 'long') === props.form))
const ready = computed(() => mine.value.filter(p => !isProjectDraft(p)))
const drafts = computed(() => mine.value.filter(isProjectDraft))

async function loadProjects() {
  if (props.guest) { projects.value = []; return }
  const id = ++loadId
  error.value = null
  try {
    const list = await api.listProjects()
    if (alive && id === loadId) projects.value = list
  } catch (err) {
    if (alive && id === loadId) error.value = formatApiError(err, '加载失败')
  }
}
async function deleteProject(project: Project) {
  if (props.guest || deleting.value.has(project.id)) return
  if (!window.confirm(`删除《${project.title}》？全书正文、记忆、向量与任务记录将一并移除，不可撤销。`)) return
  deleting.value.add(project.id)
  try {
    await api.deleteProject(project.id)
    if (!alive) return
    deleteError.value = null
    await loadProjects()
  } catch (err) {
    if (!alive) return
    deleteError.value = err instanceof ApiError && err.status === 409
      ? `《${project.title}》有进行中任务，无法删除。请先暂停/取消后再试。`
      : formatApiError(err, '删除失败')
  } finally {
    if (alive) deleting.value.delete(project.id)
  }
}
onMounted(() => { void loadProjects() })
onScopeDispose(() => { alive = false; loadId++ })
</script>

<template>
  <div :class="styles.wrap">
    <ProjectRail v-if="auth" :projects="projects ?? []" />
    <aside v-else :class="rail.rail" data-guest-exempt>
      <RouterLink to="/long" :class="rail.brand">Myink</RouterLink>
      <nav :class="rail.sections" aria-label="作品分区">
        <RouterLink to="/long" :class="form === 'long' ? rail.sectionCurrent : rail.sectionItem" :aria-current="form === 'long' ? 'true' : undefined">长篇</RouterLink>
        <RouterLink to="/short" :class="form === 'short' ? rail.sectionCurrent : rail.sectionItem" :aria-current="form === 'short' ? 'true' : undefined">短篇</RouterLink>
      </nav>
      <nav :class="rail.nav" aria-label="作品列表">
        <RouterLink v-for="project in ready" :key="project.id" :to="projectHref(project)" :class="rail.item">
          <span :class="rail.title">{{ project.title }}</span>
        </RouterLink>
      </nav>
      <nav :class="rail.pageLinks" aria-label="全局页面">
        <RouterLink to="/environment" :class="rail.item">高级设置</RouterLink>
        <RouterLink to="/theme" :class="rail.item">主题</RouterLink>
        <RouterLink to="/writing-resources" :class="rail.item">写作资源</RouterLink>
      </nav>
      <div :class="rail.foot">
        <RouterLink to="/account" :class="rail.item">账号</RouterLink>
        <div :class="rail.userRow"><span :class="rail.user">{{ username }}</span><RouterLink v-if="guest" to="/login" class="btn btn-quiet">登录</RouterLink><button v-else type="button" class="btn btn-quiet" @click="$emit('logout')">登出</button></div>
      </div>
    </aside>
    <main :class="styles.main">
      <div :class="styles.head">
        <h1>{{ label }}</h1>
        <RouterLink :to="`/${form}/new`" class="btn btn-primary">新建{{ label }}</RouterLink>
      </div>
      <div v-if="error" role="alert" class="banner banner-error">加载失败：{{ error }} <button type="button" class="btn btn-quiet" @click="loadProjects">重试</button></div>
      <div v-if="deleteError" role="alert" class="banner banner-error">{{ deleteError }}</div>
      <div v-if="projects === null && !error" class="empty">加载中…</div>
      <div v-else-if="projects !== null && mine.length === 0" class="empty">还没有{{ label }}作品。点击右上角「新建{{ label }}」，一句话梗概即可创建第一本。</div>
      <template v-else-if="projects !== null">
        <h2 :class="styles.sectionTitle">正式作品</h2>
        <p v-if="ready.length === 0" class="empty">尚无已完成建书的作品，请先完成下方草稿。</p>
        <ul :class="styles.list">
          <li v-for="project in ready" :key="project.id" :class="styles.row">
            <RouterLink :to="projectHref(project)" :class="styles.rowLink">
              <span :class="styles.title">{{ project.title }}</span><span :class="styles.meta">{{ project.genre }} · 已写至第 {{ project.current_chapter }} 章</span><span :class="styles.arrow" aria-hidden="true">→</span>
            </RouterLink>
            <button type="button" :class="styles.del" :disabled="deleting.has(project.id)" :aria-label="`删除《${project.title}》`" @click="deleteProject(project)">删除</button>
          </li>
        </ul>
        <section v-if="drafts.length" aria-label="待完成作品">
          <h2 :class="styles.sectionTitle">待完成作品</h2>
          <ul :class="styles.list">
            <li v-for="project in drafts" :key="project.id" :class="styles.row">
              <RouterLink :to="projectHref(project)" :class="styles.rowLink">
                <span :class="styles.title">{{ project.title }}</span><span :class="styles.meta">{{ project.creation_status === 'setup_confirmed' ? '设定已确认 · 待确认大纲' : '待完成设定与大纲' }}</span><span :class="styles.arrow" aria-hidden="true">→</span>
              </RouterLink>
            </li>
          </ul>
        </section>
      </template>
    </main>
  </div>
</template>
