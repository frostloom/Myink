<script setup lang="ts">
import { computed, onScopeDispose, ref, watch } from 'vue'
import { useAuth } from '../authContext'
import { useMemoryFormGuard } from '../composables/useMemoryFormGuard'
import { styleLibraryApi, type StyleLibraryItem } from '../../../src/lib/styleLibraryApi'
import { writingResources, resourceError, type ResourceBody, type WritingResource } from '../../../src/lib/writingResources'
import { ResourceBodyFields } from '../pages/admin/ResourceBodyFields'
import local from './UserResourceCatalog.module.css'

const emit = defineEmits<{ saved: [] }>()
const { session, status } = useAuth()
const open = ref(false), sample = ref(''), name = ref(''), profile = ref<Record<string, unknown> | null>(null)
const publishForAll = ref(false), pending = ref<WritingResource | null>(null)
const busy = ref(false), error = ref(''), notice = ref(''), legacy = ref<StyleLibraryItem[] | null>(null)
const admin = computed(() => session.value?.role === 'admin' && session.value.roleVerified === true)
let generation = 0
const active = (request: number) => request === generation && status.value === 'authenticated' && !!session.value?.userId
function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical)
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, canonical(item)]))
  return value
}
function clear() { open.value = false; sample.value = ''; name.value = ''; profile.value = null; publishForAll.value = false; pending.value = null; error.value = '' }
watch(() => [session.value?.userId, session.value?.role, session.value?.roleVerified, status.value], () => {
  generation++; busy.value = false; legacy.value = null; notice.value = ''; clear()
}, { flush: 'sync' })
onScopeDispose(() => { generation++ })
useMemoryFormGuard(() => open.value && !!(sample.value.trim() || name.value.trim() || profile.value || pending.value))

async function extract() {
  if (busy.value || !sample.value.trim() || !session.value?.token) return
  const request = generation, text = sample.value
  busy.value = true; error.value = ''; notice.value = ''; profile.value = null
  try {
    const result = await styleLibraryApi.extract(session.value.token, [text])
    if (!active(request)) return
    const { extract_error, ...draft } = result.draft
    profile.value = draft
    if (extract_error) error.value = `语义提取未完成，当前仅有统计结果：${String(extract_error)}`
  } catch (cause) { if (active(request)) error.value = resourceError(cause) }
  finally { if (active(request)) busy.value = false }
}
async function save() {
  if (busy.value || !profile.value || !name.value.trim()) return
  const request = generation
  busy.value = true; error.value = ''; notice.value = ''
  try {
    if (pending.value) {
      if (!admin.value) throw new Error('管理员身份已变化，请重新登录后发布。')
      await writingResources.publish(pending.value.id, pending.value.generation, '从文章提取的文风')
    } else {
      const input = { name: name.value.trim(), kind: 'style' as const, source: '文章样本提取', body: { profile: profile.value } }
      if (publishForAll.value && admin.value) {
        const draft = await writingResources.create(input)
        if (!active(request) || !admin.value) return
        pending.value = draft
        await writingResources.publish(draft.id, draft.generation, '从文章提取的文风')
      } else {
        await writingResources.createPersonal(input)
      }
    }
    if (!active(request)) return
    notice.value = pending.value ? '文风已发布，所有用户均可选用。' : '文风已保存，仅你可用。'
    clear(); emit('saved')
  } catch (cause) {
    if (!active(request)) return
    if (pending.value) {
      try {
        const expected = pending.value
        const published = (await writingResources.catalogAll()).items.find(item => item.id === expected.id)
        if (!active(request)) return
        if (published && published.name === expected.name && published.source === expected.source && JSON.stringify(canonical(published.body)) === JSON.stringify(canonical(expected.body))) {
          notice.value = '文风已发布，所有用户均可选用。'; clear(); emit('saved'); return
        }
      } catch { /* A disconnected catalog leaves the publication state uncertain. */ }
      if (!active(request)) return
      error.value = `平台资源已保存，发布状态待确认；可重试或到管理后台核对：${resourceError(cause)}`
    } else error.value = resourceError(cause)
  }
  finally { if (active(request)) busy.value = false }
}
async function loadLegacy() {
  if (busy.value || !session.value?.token) return
  const request = generation; busy.value = true; error.value = ''; notice.value = ''
  try {
    const [result, mine] = await Promise.all([styleLibraryApi.list(session.value.token), writingResources.personal()])
    const imported = new Set(mine.items.map(item => item.source_resource_id))
    if (active(request)) legacy.value = result.items.filter(item => !item.builtin && !imported.has(`legacy-style:${item.id}`))
  } catch (cause) { if (active(request)) error.value = resourceError(cause) }
  finally { if (active(request)) busy.value = false }
}
async function importLegacy(item: StyleLibraryItem) {
  if (busy.value) return
  const request = generation; busy.value = true; error.value = ''; notice.value = ''
  try {
    await writingResources.importLegacy(item.id)
    if (!active(request)) return
    legacy.value = legacy.value?.filter(entry => entry.id !== item.id) ?? null
    notice.value = `“${item.name}”已复制到你的写作资源。`; emit('saved')
  } catch (cause) { if (active(request)) error.value = resourceError(cause) }
  finally { if (active(request)) busy.value = false }
}
</script>
<template>
  <section :class="local.extract" aria-label="文风提取">
    <div :class="local.extractActions">
      <button class="btn btn-primary" :disabled="busy || open" @click="open=true; notice=''; error=''">从文章提取文风</button>
      <button class="btn btn-quiet" :disabled="busy" @click="loadLegacy">导入旧版个人文风</button>
    </div>
    <p :class="local.note">粘贴文章提取表达特点，保存为写作资源后可在长篇和短篇中选用。</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <div v-if="legacy !== null" :class="local.legacy">
      <p v-if="!legacy.length">没有待导入的旧版个人文风。</p>
      <div v-for="item in legacy" :key="item.id" :class="local.extractActions"><span>{{ item.name }}</span><button class="btn btn-quiet" :aria-label="`导入 ${item.name}`" :disabled="busy" @click="importLegacy(item)">导入</button></div>
    </div>
    <form v-if="open" :class="local.extractForm" @submit.prevent="save">
      <label>文章样本<textarea v-model="sample" class="textarea" aria-label="文章样本" maxlength="12000" rows="6" :disabled="busy || !!pending" @input="profile=null" /></label>
      <p :class="local.note">最多 12000 字；样本将发送给当前配置的模型分析。</p>
      <button type="button" class="btn btn-secondary" :disabled="busy || !!pending || !sample.trim()" @click="extract">{{ busy && !profile ? '提取中…' : '提取文风' }}</button>
      <template v-if="profile">
        <label>文风名称<input v-model="name" class="input" aria-label="文风名称" maxlength="64" :disabled="busy || !!pending" required /></label>
        <fieldset :disabled="busy || !!pending" :class="local.extractFields">
          <legend>检查并调整提取结果</legend>
          <ResourceBodyFields kind="style" :value="{profile}" :on-change="(value: ResourceBody) => { if ('profile' in value) profile = value.profile }" />
        </fieldset>
        <label v-if="admin" :class="local.publishChoice"><input v-model="publishForAll" type="checkbox" aria-label="发布给所有用户" :disabled="busy || !!pending" />发布给所有用户</label>
        <p v-if="admin" :class="local.note">勾选后，文风内容及其中的样本摘录对所有用户可见；不勾选则仅自己可用。</p>
      </template>
      <div :class="local.extractActions">
        <button type="button" class="btn btn-quiet" :disabled="busy" @click="clear">{{ pending ? '关闭（平台草稿已保存）' : '取消' }}</button>
        <button v-if="profile" type="submit" class="btn btn-primary" :disabled="busy || !name.trim()">{{ pending ? '重试发布' : busy ? '保存中…' : '保存文风' }}</button>
      </div>
    </form>
  </section>
</template>
