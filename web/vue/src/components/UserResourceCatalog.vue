<script setup lang="ts">
import {computed,onScopeDispose,ref,watch} from 'vue'
import {writingResources as api,resourceKinds,resourceError,type WritingResource,type ResourceBody,type SelectionInput,type ResourceKind,type ResourceSelection} from '../../../src/lib/writingResources'
import {resourceTitle,resourceSummary,isSupportingReference,isLegacyRoleSupplement} from '../../../src/lib/resourceDisplay'
import {AdminDialog} from '../pages/admin/AdminDialog'
import {ResourceBodyFields} from '../pages/admin/ResourceBodyFields'
import {ResourceContent} from '../pages/admin/ResourceContent'
import {useMemoryFormGuard} from '../composables/useMemoryFormGuard'
import styles from '../../../src/pages/admin/AdminResources.module.css'
import local from './UserResourceCatalog.module.css'
type CatalogResource = WritingResource & {bookOrigin?:'platform'|'personal';bookCurrent?:boolean}
const props=withDefaults(defineProps<{mode?:'library'|'choose';contained?:boolean;initialSelection?:SelectionInput[];currentResources?:ResourceSelection[]}>(),{mode:'library',contained:false,initialSelection:undefined,currentResources:undefined})
const emit=defineEmits<{'update:selection':[SelectionInput[]];ready:[boolean]}>()
const platform=ref<WritingResource[]>([]),personal=ref<WritingResource[]>([]),loading=ref(true),error=ref(''),busy=ref(false),query=ref(''),filter=ref('all')
const choices=ref<SelectionInput[]>([])
const editedChoices=ref<Record<string,SelectionInput>>({})
const editing=ref<WritingResource|null>(null),preview=ref<WritingResource|null>(null),syncing=ref<WritingResource|null>(null)
const draftName=ref(''),draftBody=ref<ResourceBody>({roles:{}}),draftError=ref(''),conflict=ref(false),reloadConfirm=ref(false)
const isConflict=(cause:unknown)=>typeof cause==='object'&&cause!==null&&'status' in cause&&cause.status===409
let version=0
const automaticRule=(kind:ResourceKind)=>['writing_rule','expression_rule'].includes(kind)
const rootId=(item:WritingResource)=>item.source_resource_id??personal.value.find(row=>row.id===item.id)?.source_resource_id??item.id
const choiceRoot=(choice:SelectionInput)=>choice.origin==='personal'?(personal.value.find(row=>row.id===choice.resource_id)?.source_resource_id??choice.resource_id):choice.resource_id
const automatic=(kind:ResourceKind)=>['genre','genre_rule','role_prompt','reference'].includes(kind)
const isPersonal=(item:CatalogResource)=>item.bookOrigin?item.bookOrigin==='personal':personal.value.some(p=>p.id===item.id)
const origin=(item:WritingResource):'personal'|'platform'=>isPersonal(item)?'personal':'platform'
const selectable=(item:WritingResource)=>!automatic(item.kind)
const resources=computed<CatalogResource[]>(()=>{
 const explicit=props.initialSelection!==undefined
 const items:CatalogResource[]=explicit?[...platform.value,...personal.value]:[
  ...platform.value.map(item=>personal.value.find(own=>own.source_resource_id===item.id)??item),
  ...personal.value.filter(item=>!item.source_resource_id||!platform.value.some(p=>p.id===item.source_resource_id)),
 ]
 for(const saved of props.currentResources??[]){
  const index=items.findIndex(item=>item.id===saved.resource_id&&origin(item)===saved.origin)
  const frozen:CatalogResource={id:saved.resource_id,name:saved.name,kind:saved.kind,source:'本书快照',status:'published',generation:saved.generation,current_version:saved.version,body:saved.body,bookOrigin:saved.origin,bookCurrent:true}
  if(index<0)items.push(frozen);else items[index]=frozen
 }
 return items.map(item=>{
  const current=props.initialSelection?.find(c=>c.resource_id===item.id&&c.origin===origin(item))
  return current?{...item,bookCurrent:true,...(current.personal_override&&current.body?{body:current.body}:{})}:item
 }).filter(item=>!isSupportingReference(item)&&!isLegacyRoleSupplement(item)&&(props.mode!=='choose'||selectable(item)))
})
const matched=computed(()=>resources.value.filter(item=>`${item.name} ${resourceTitle(item)} ${resourceSummary(item.body)}`.toLowerCase().includes(query.value.trim().toLowerCase())))
const shown=computed(()=>matched.value.filter(item=>filter.value==='all'||item.kind===filter.value))
const kinds=computed(()=>Object.entries(resourceKinds).filter(([kind])=>props.mode==='library'||!automatic(kind as ResourceKind)))
function clearFilters(){query.value='';filter.value='all'}
const selected=(item:WritingResource)=>choices.value.some(c=>c.resource_id===item.id&&c.origin===origin(item))
const source=(item:WritingResource)=>platform.value.find(p=>p.id===item.source_resource_id)
const hasUpdate=(item:WritingResource)=>Boolean(source(item)&&source(item)!.generation!==item.source_generation)
function emitChoices(){emit('update:selection',choices.value.map(c=>({...c})))}
async function load(){
 const request=++version;loading.value=true;error.value='';emit('ready',false)
 try{
  const [catalog,mine]=await Promise.all([api.catalogAll(),api.personal()]);if(request!==version)return
  platform.value=catalog.items;personal.value=mine.items
  const initial=props.initialSelection
  choices.value=initial===undefined?resources.value.filter(item=>['writing_rule','expression_rule'].includes(item.kind)).map(item=>({origin:origin(item),resource_id:item.id})):JSON.parse(JSON.stringify(initial))
  emitChoices();emit('ready',true)
 }catch(cause){if(request===version)error.value=resourceError(cause)}finally{if(request===version)loading.value=false}
}
watch(()=>props.mode,()=>void load(),{immediate:true})
onScopeDispose(()=>{version++})
useMemoryFormGuard(()=>editing.value!==null)
function toggle(item:WritingResource){
 const original=editedChoices.value[`${origin(item)}:${item.id}`]??props.initialSelection?.find(c=>c.resource_id===item.id&&c.origin===origin(item))
 const choice=original?JSON.parse(JSON.stringify(original)):{origin:origin(item),resource_id:item.id}
 const remaining=automaticRule(item.kind)?choices.value.filter(c=>choiceRoot(c)!==rootId(item)):choices.value
 choices.value=selected(item)?choices.value.filter(c=>c.resource_id!==item.id||c.origin!==origin(item)):[...remaining,choice];emitChoices()
}
function edit(item:WritingResource){draftName.value=item.name;draftBody.value=JSON.parse(JSON.stringify(item.body));draftError.value='';conflict.value=false;editing.value=item}
function remember(saved:WritingResource,previous:WritingResource){
 const choice:SelectionInput={origin:'personal',resource_id:saved.id,personal_override:true,body:JSON.parse(JSON.stringify(saved.body))}
 editedChoices.value[`personal:${saved.id}`]=choice
 personal.value=[...personal.value.filter(p=>p.id!==saved.id&&(!saved.source_resource_id||p.source_resource_id!==saved.source_resource_id)),saved]
 if(props.mode==='choose'&&automaticRule(saved.kind)){
  const related=rootId(saved)
  const wasSelected=choices.value.some(choice=>choiceRoot(choice)===related)
  choices.value=choices.value.filter(choice=>choiceRoot(choice)!==related)
  if(wasSelected)choices.value.push(choice)
 }else choices.value=choices.value.map(c=>c.resource_id===previous.id&&c.origin===origin(previous)?choice:c)
 emitChoices()
}
async function save(){
 if(!editing.value||busy.value||conflict.value)return
 const item=editing.value,request=version;busy.value=true;draftError.value=''
 try{
  const saved=isPersonal(item)?await api.savePersonal(item.id,{name:draftName.value,source:item.source,body:draftBody.value,expected_generation:item.generation}):await api.forkPersonal(item.id,{name:draftName.value,body:draftBody.value,target_generation:item.generation})
  if(request!==version)return;remember(saved,item);editing.value=null
 }catch(cause){if(request===version){draftError.value=resourceError(cause);conflict.value=isConflict(cause)}}finally{if(request===version)busy.value=false}
}
async function sync(){
 const item=syncing.value,target=item&&source(item);if(!item||!target||busy.value||conflict.value)return
 const request=version;busy.value=true;draftError.value=''
 try{const saved=await api.syncPersonal(item.id,item.generation,target.generation);if(request!==version)return;remember(saved,item);syncing.value=null}
 catch(cause){if(request===version){draftError.value=resourceError(cause);conflict.value=isConflict(cause)}}finally{if(request===version)busy.value=false}
}
function requestSync(item:WritingResource){syncing.value=item;draftError.value='';conflict.value=false}
async function reloadLatest(){
 if(busy.value)return
 const request=version,item=editing.value??syncing.value;if(!item)return
 const wasPersonal=isPersonal(item);busy.value=true;reloadConfirm.value=false
 try{
  const [catalog,mine]=await Promise.all([api.catalogAll(),api.personal()]);if(request!==version)return
  const latest=wasPersonal?mine.items.find(row=>row.id===item.id):mine.items.find(row=>row.source_resource_id===item.id)??catalog.items.find(row=>row.id===item.id)
  if(!latest||(syncing.value&&!catalog.items.some(row=>row.id===latest.source_resource_id)))throw new Error('资源已不可用，请保留当前内容后关闭重试。')
  platform.value=catalog.items;personal.value=mine.items
  if(editing.value){editing.value=latest;draftName.value=latest.name;draftBody.value=JSON.parse(JSON.stringify(latest.body))}
  else syncing.value=latest
  draftError.value='';conflict.value=false
 }catch(cause){if(request===version)draftError.value=resourceError(cause)}finally{if(request===version)busy.value=false}
}
const roleBody=computed(()=> 'role' in draftBody.value?draftBody.value:null)
</script>
<template>
 <section :class="local.catalog" :aria-label="mode==='choose'?'建书写作资源':'个人写作资源库'">
  <p v-if="mode==='choose'" :class="local.note">创作规则和表达规则默认勾选，可取消或编辑后保存为你的版本；文风可自由选择。题材相关资源按本书题材自动匹配。</p>
  <p v-else :class="local.note">编辑后保存为你的版本，之后建书和自动资源会优先选用。已建立的作品继续保留原快照。</p>
  <p v-if="loading" role="status">正在加载写作资源…</p>
  <p v-if="error" role="alert">{{ error }} <button class="btn" @click="load">重试</button></p>
  <template v-if="!loading&&!error">
   <div :class="local.toolbar"><input v-model="query" class="input" aria-label="搜索写作资源" placeholder="搜索创作环节、题材、文风或规则…" /></div>
   <div :class="[styles.resourceTabs,local.categories]" role="group" aria-label="资源类型筛选">
    <button class="btn btn-quiet" aria-label="全部" :aria-pressed="filter==='all'" @click="filter='all'">全部<span>{{ matched.length }}</span></button>
    <button v-for="[kind,label] in kinds" :key="kind" class="btn btn-quiet" :aria-label="label" :aria-pressed="filter===kind" @click="filter=kind">{{ label }}<span>{{ matched.filter(item=>item.kind===kind).length }}</span></button>
   </div>
   <p :class="local.note" role="status">共 {{ shown.length }} 张卡片</p>
   <div :class="[local.listScroll,contained&&local.unboundedScroll]">
   <div :class="[styles.resourceGrid,local.grid]">
    <article v-for="item in shown" :key="`${origin(item)}:${item.id}`" :class="[styles.card,styles.resourceCard,local.card,mode==='choose'&&selected(item)&&local.selected]">
     <div :class="styles.resourceBadges"><span>{{ resourceKinds[item.kind] }}</span><span>{{ item.bookCurrent?'本书现用版本':isPersonal(item)?'我的版本':'平台版本' }} · v{{ item.current_version }}</span></div>
     <h3 :class="styles.cardTitle">{{ resourceTitle(item) }}</h3>
     <p :class="styles.preview">{{ resourceSummary(item.body)||'查看内容并按你的习惯调整' }}</p>
     <p v-if="mode==='library'&&automatic(item.kind)" :class="local.note">{{ item.kind==='genre'||item.kind==='genre_rule'?'按作品题材自动匹配':'按创作环节自动使用' }}</p>
     <footer :class="local.actions">
      <label v-if="mode==='choose'" :class="local.choose"><input type="checkbox" :checked="selected(item)" :aria-label="`选用 ${item.name}`" @change="toggle(item)" />选用</label>
      <button class="btn btn-quiet" :aria-label="`查看 ${item.name}`" @click="preview=item">查看</button>
      <button v-if="!item.bookCurrent" class="btn btn-quiet" :aria-label="`编辑 ${item.name}`" @click="edit(item)">编辑</button>
      <button v-if="hasUpdate(item)" class="btn btn-secondary" :aria-label="`更新 ${item.name}`" @click="requestSync(item)">平台有更新</button>
     </footer>
    </article>
   </div>
   </div>
   <template v-if="mode==='choose'">
    <p v-if="!resources.some(item=>item.kind==='writing_rule')" :class="local.note">平台尚未配置创作规则。</p>
    <p v-if="!resources.some(item=>item.kind==='expression_rule')" :class="local.note">平台尚未配置表达规则。</p>
   </template>
   <div v-if="!shown.length" class="empty"><p>没有符合条件的资源。</p><button v-if="query||filter!=='all'" class="btn btn-secondary" @click="clearFilters">清除筛选</button></div>
  </template>
  <AdminDialog v-if="preview" :title="preview.name" :busy="false" :on-close="()=>preview=null"><ResourceContent :body="preview.body" /></AdminDialog>
  <AdminDialog v-if="editing" :title="`编辑 ${editing.name}`" :busy="busy" :on-close="()=>editing=null">
   <form :class="[styles.resourceFields,local.editor]" @submit.prevent="save">
    <p>保存只影响你的资源版本，不会修改平台原文。</p>
    <fieldset :class="local.editorBody" :disabled="busy">
    <label>资源名称<input v-model="draftName" class="input" required /></label>
    <template v-if="roleBody">
     <label v-for="(value,key,index) in roleBody.templates" :key="key">创作环节 {{ index+1 }}<textarea class="textarea" :value="value" rows="7" @input="draftBody={...roleBody!,templates:{...roleBody!.templates,[key]:($event.target as HTMLTextAreaElement).value}}" /></label>
     <label>共用补充<textarea class="textarea" :value="roleBody.supplement??''" rows="4" @input="draftBody={...roleBody!,supplement:($event.target as HTMLTextAreaElement).value}" /></label>
    </template>
    <ResourceBodyFields v-else :kind="editing.kind" :value="draftBody" :on-change="value=>draftBody=value" />
    </fieldset><p v-if="draftError" role="alert">{{ draftError }}</p><button v-if="conflict" type="button" class="btn btn-secondary" :disabled="busy" @click="reloadConfirm=true">重新载入最新版本</button>
    <div :class="styles.actions"><button class="btn" type="button" :disabled="busy" @click="editing=null">取消</button><button class="btn btn-primary" :disabled="busy||conflict||!draftName.trim()">{{ busy?'保存中…':'保存为我的版本' }}</button></div>
   </form>
  </AdminDialog>
  <AdminDialog v-if="syncing" title="更新我的资源版本" :busy="busy" :on-close="()=>syncing=null">
   <p>采用平台最新版本将覆盖你对这份资源的个人修改。已经建立的作品和正在运行的任务仍保留原快照。</p>
   <ResourceContent :body="source(syncing)!.body" />
   <p v-if="draftError" role="alert">{{ draftError }}</p><button v-if="conflict" type="button" class="btn btn-secondary" :disabled="busy" @click="reloadConfirm=true">重新载入最新版本</button>
   <div :class="styles.actions"><button class="btn" :disabled="busy" @click="syncing=null">保留我的修改</button><button class="btn btn-primary" :disabled="busy||conflict" @click="sync">确认覆盖我的修改</button></div>
  </AdminDialog>
  <AdminDialog v-if="reloadConfirm" title="重新载入最新版本" :busy="busy" :on-close="()=>reloadConfirm=false">
   <p>重新载入会放弃当前未保存修改，并显示最新内容。请先复制需要保留的文字；载入后仍需重新确认保存或覆盖。</p>
   <div :class="styles.actions"><button class="btn" @click="reloadConfirm=false">保留当前修改</button><button class="btn btn-primary" @click="reloadLatest">放弃修改并重新载入</button></div>
  </AdminDialog>
 </section>
</template>
