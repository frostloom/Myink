<script setup lang="ts">
import { computed, onScopeDispose, ref, watch } from 'vue'
import { writingResources as api, resourceKinds, resourceError, type ResourceBody, type ResourceSelection, type ResourceSnapshot, type SelectionInput } from '../../../src/lib/writingResources'
import { type BookGenrePack } from '../../../src/lib/genrePacks'
import { resourceSummary } from '../../../src/lib/resourceDisplay'
import { AdminDialog } from '../pages/admin/AdminDialog'
import { ResourceContent } from '../pages/admin/ResourceContent'
import { ResourceBodyFields } from '../pages/admin/ResourceBodyFields'
import ResourceUpdates from './ResourceUpdates.vue'
import UserResourceCatalog from './UserResourceCatalog.vue'
import { useMemoryFormGuard } from '../composables/useMemoryFormGuard'
import styles from '../../../src/pages/admin/AdminResources.module.css'
import local from './ProjectWritingSettings.module.css'
const props = defineProps<{projectId: string; genrePack: BookGenrePack | null}>()
const snapshot = ref<ResourceSnapshot | null>(null), error = ref(''), notice = ref(''), loading = ref(true), busy = ref(false)
const editing = ref<ResourceSelection | null>(null), preview = ref<ResourceSelection | null>(null), choosing = ref(false), ready = ref(false)
const draft = ref<ResourceBody>({profile:{}}), draftError = ref(''), choices = ref<SelectionInput[]>([]), conflict = ref(false), reloadConfirm = ref(false)
const isConflict=(cause:unknown)=>typeof cause==='object'&&cause!==null&&'status' in cause&&cause.status===409
const chooserRevision=ref(0)
let version = 0
const optional = computed(() => snapshot.value?.selections.filter(item => ['style','writing_rule','expression_rule'].includes(item.kind)) ?? [])
const genres = computed(() => snapshot.value?.selections.filter(item => ['genre','genre_rule'].includes(item.kind)) ?? [])
const legacyBody = computed<ResourceBody | null>(() => {
 const pack=props.genrePack;if(!pack)return null
 const {selling_point,subgenres,taboos,pacing,satisfaction,mechanics,world_hints}=pack
 return {catalog_id:pack.source_id ?? '',fields:{selling_point,subgenres,taboos,pacing,satisfaction,mechanics,world_hints},setup_caps:pack.setup_caps}
})
const groups = ['style','writing_rule','expression_rule'] as const
const legacyPreview = ref(false)
const selection = (item:ResourceSelection):SelectionInput => ({origin:item.origin,resource_id:item.resource_id,...(item.personal_override ? {personal_override:true,body:item.body} : {})})
const initialSelection = computed(() => optional.value.map(selection))
async function load() {
 const request=++version, pid=props.projectId;loading.value=true;error.value='';snapshot.value=null
 try { const saved=await api.snapshot(pid);if(request===version)snapshot.value=saved }
 catch(cause){if(request===version)error.value=resourceError(cause)}
 finally{if(request===version)loading.value=false}
}
watch(()=>props.projectId,()=>{editing.value=null;preview.value=null;legacyPreview.value=false;choosing.value=false;busy.value=false;notice.value='';conflict.value=false;reloadConfirm.value=false;void load()},{immediate:true})
onScopeDispose(()=>{version++})
useMemoryFormGuard(()=>editing.value!==null||choosing.value)
function edit(item:ResourceSelection){editing.value=item;draft.value=JSON.parse(JSON.stringify(item.body));draftError.value='';conflict.value=false}
function choose(){choosing.value=true;ready.value=false;draftError.value='';conflict.value=false;choices.value=initialSelection.value.map(item=>({...item}))}
async function save(selections:SelectionInput[]) {
 if(!snapshot.value||busy.value||conflict.value)return
 const request=version,pid=props.projectId;busy.value=true;draftError.value='';notice.value=''
 try {
  const saved=await api.select(pid,snapshot.value.revision,selections)
  if(request!==version)return
  snapshot.value=saved;editing.value=null;choosing.value=false
  notice.value='资源已保存，对后续新任务生效；历史章节和运行中的任务保持不变。'
 }catch(cause){if(request===version){draftError.value=resourceError(cause);conflict.value=isConflict(cause)}}
 finally{if(request===version)busy.value=false}
}
function saveEdit(){
 const item=editing.value;if(!item)return
 void save(optional.value.map(old=>old.origin===item.origin&&old.resource_id===item.resource_id?{origin:old.origin,resource_id:old.resource_id,personal_override:true,body:draft.value}:selection(old)))
}
function saveChoices(){
 if(!ready.value)return
 void save(choices.value.map(choice=>{
  const old=optional.value.find(item=>item.origin===choice.origin&&item.resource_id===choice.resource_id)
  return choice.personal_override&&choice.body?choice:old?.personal_override?selection(old):choice
 }))
}
async function reloadLatest(){
 if(busy.value)return
 const request=version,pid=props.projectId,item=editing.value;busy.value=true;reloadConfirm.value=false
 try{
  const saved=await api.snapshot(pid);if(request!==version)return
  snapshot.value=saved;draftError.value='';conflict.value=false
  if(item){
   const latest=saved.selections.find(row=>row.origin===item.origin&&row.resource_id===item.resource_id)
   if(latest){editing.value=latest;draft.value=JSON.parse(JSON.stringify(latest.body))}
   else{editing.value=null;notice.value='这份资源已从本书移除，请重新选择需要的资源。'}
  }
  if(choosing.value){ready.value=false;chooserRevision.value++;choices.value=initialSelection.value.map(row=>({...row}))}
 }catch(cause){if(request===version)draftError.value=resourceError(cause)}finally{if(request===version)busy.value=false}
}

</script>
<template>
 <p v-if="loading" role="status">正在加载本书创作资源…</p>
 <p v-if="error" class="banner banner-error" role="alert">{{ error }} <button class="btn" @click="load">重新加载</button></p>
 <template v-if="!loading&&!error">
  <section :class="local.section" aria-label="本书题材">
   <h2>本书题材</h2><p :class="local.note">当前作品采用的题材与规则，只读展示。</p>
   <div :class="[styles.resourceGrid,local.grid]">
<article v-for="item in genres" :key="`${item.origin}:${item.resource_id}`" :class="[styles.card,styles.resourceCard,local.card]">
    <div :class="styles.resourceBadges"><span>{{ resourceKinds[item.kind] }}</span><span>v{{ item.version }}</span><span>只读</span></div>
    <h3 :class="styles.cardTitle">{{ item.name }}</h3><p :class="styles.preview">{{ resourceSummary(item.body) }}</p><div :class="styles.actions"><button class="btn btn-quiet" :aria-label="`查看 ${item.name}`" @click="preview=item">查看</button></div>
   </article>
   <article v-if="!genres.some(item=>item.kind==='genre')&&legacyBody" :class="[styles.card,styles.resourceCard,local.card]">
    <div :class="styles.resourceBadges"><span>题材</span><span>只读</span></div><h3 :class="styles.cardTitle">{{ genrePack?.source_name }}{{ genrePack?.secondary_name?` + ${genrePack.secondary_name}`:'' }}</h3><p :class="styles.preview">{{ resourceSummary(legacyBody) }}</p><div :class="styles.actions"><button class="btn btn-quiet" :aria-label="`查看 ${genrePack?.source_name}`" @click="legacyPreview=true">查看</button></div>
   </article>
   <p v-else-if="!genres.length&&!legacyBody" :class="local.note">本书未配置题材包。</p>
</div>
  </section>
  <section :class="local.section" aria-label="本书写作资源">
   <div :class="local.heading"><h2>写作资源</h2><button class="btn btn-secondary" @click="choose">调整资源选择</button></div>
   <p :class="local.note">创作规则和表达规则默认选用，可调整选择并在卡片中编辑；文风可自由选择。保存只对后续新任务生效，不改动历史章节和运行中的任务。</p>
   <p v-if="notice" class="banner" role="status">{{ notice }}</p>
   <section v-for="kind in groups" :key="kind" :class="local.section" :aria-label="resourceKinds[kind]">
<h3>{{ resourceKinds[kind] }}</h3><div :class="[styles.resourceGrid,local.grid]">
    <article v-for="item in optional.filter(row=>row.kind===kind)" :key="`${item.origin}:${item.resource_id}`" :class="[styles.card,styles.resourceCard,local.card]">
     <div :class="styles.resourceBadges"><span>{{ resourceKinds[item.kind] }}</span><span>{{ item.personal_override?'本书修改版':item.origin==='personal'?'个人版本':'平台版本' }} · v{{ item.version }}</span></div>
     <h3 :class="styles.cardTitle">{{ item.name }}</h3><p :class="styles.preview">{{ resourceSummary(item.body) }}</p>
     <div :class="styles.actions"><button class="btn btn-quiet" :aria-label="`查看 ${item.name}`" @click="preview=item">查看</button><button class="btn btn-quiet" :aria-label="`编辑 ${item.name}`" @click="edit(item)">编辑</button></div>
    </article>
   </div><p v-if="!optional.some(item=>item.kind===kind)" :class="local.note">尚未选用{{ resourceKinds[kind] }}，可调整资源选择。</p>
</section>
  </section>
  <ResourceUpdates :paused="Boolean(editing||preview||choosing||legacyPreview||reloadConfirm)" :project-id="projectId" :on-adopt="saved=>snapshot=saved" />
 </template>
 <AdminDialog v-if="legacyPreview&&legacyBody" :title="genrePack?.source_name ?? '题材'" :busy="false" :on-close="()=>legacyPreview=false"><ResourceContent :body="legacyBody" /></AdminDialog>
 <AdminDialog v-if="preview" :title="preview.name" :busy="false" :on-close="()=>preview=null"><ResourceContent :body="preview.body" /></AdminDialog>
 <AdminDialog v-if="editing" :title="`编辑 ${editing.name}`" :busy="busy" :on-close="()=>editing=null">
  <form :class="[styles.resourceFields,local.editor]" @submit.prevent="saveEdit">
   <p>保存为本书修改版，仅对后续新任务生效。</p>
   <fieldset :disabled="busy"><ResourceBodyFields :kind="editing.kind" :value="draft" :on-change="value=>draft=value" /></fieldset>
   <p v-if="draftError" role="alert">{{ draftError }}</p><button v-if="conflict" type="button" class="btn btn-secondary" :disabled="busy" @click="reloadConfirm=true">重新载入最新版本</button>
   <div :class="styles.actions"><button type="button" class="btn" :disabled="busy" @click="editing=null">取消</button><button class="btn btn-primary" :disabled="busy||conflict">{{ busy?'保存中…':'保存本书资源' }}</button></div>
  </form>
 </AdminDialog>
 <AdminDialog v-if="choosing" title="调整本书写作资源" :busy="busy" :on-close="()=>choosing=false">
  <div :class="local.editor">
<UserResourceCatalog :key="`${snapshot?.revision}:${chooserRevision}`" mode="choose" :initial-selection="initialSelection" :current-resources="optional" @update:selection="value=>choices=value" @ready="value=>ready=value" />
   <p v-if="draftError" role="alert">{{ draftError }}</p><button v-if="conflict" type="button" class="btn btn-secondary" :disabled="busy" @click="reloadConfirm=true">重新载入最新版本</button><div :class="styles.actions"><button class="btn" :disabled="busy" @click="choosing=false">取消</button><button class="btn btn-primary" :disabled="busy||conflict||!ready" @click="saveChoices">{{ busy?'保存中…':'保存资源选择' }}</button></div>
  </div>
 </AdminDialog>
 <AdminDialog v-if="reloadConfirm" title="重新载入最新版本" :busy="busy" :on-close="()=>reloadConfirm=false">
  <p>重新载入会放弃当前未保存修改和资源勾选，并显示本书最新快照。请先复制需要保留的文字；载入后仍需重新确认保存。</p>
  <div :class="styles.actions"><button class="btn" @click="reloadConfirm=false">保留当前修改</button><button class="btn btn-primary" @click="reloadLatest">放弃修改并重新载入</button></div>
 </AdminDialog>
</template>
