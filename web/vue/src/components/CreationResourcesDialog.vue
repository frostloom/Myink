<script setup lang="ts">
import { onScopeDispose, ref, watch } from 'vue'
import WaitingStatus from './WaitingStatus.vue'
import { AdminDialog } from '../pages/admin/AdminDialog'
import UserResourceCatalog from './UserResourceCatalog.vue'
import { writingResources, resourceError, type ResourceSnapshot, type SelectionInput } from '../../../src/lib/writingResources'
const props = defineProps<{busy: boolean; error?: string | null; projectId?: string; preselectedStyle?: SelectionInput}>()
const emit = defineEmits<{confirm: [SelectionInput[]]; close: []}>()
const ready = ref(false)
const selections = ref<SelectionInput[]>([])
const snapshot = ref<ResourceSnapshot | null>(null), loading = ref(false), loadError = ref('')
let generation = 0
async function loadSnapshot() {
 const current=++generation; snapshot.value=null; loadError.value=''
 if(!props.projectId) { loading.value=false; return }
 loading.value=true
 try { const value=await writingResources.snapshot(props.projectId); if(current===generation) snapshot.value=value }
 catch(error) { if(current===generation) loadError.value=resourceError(error) }
 finally { if(current===generation) loading.value=false }
}
watch(()=>props.projectId,()=>void loadSnapshot(),{immediate:true})
onScopeDispose(()=>generation++)
function editableSelections(value:ResourceSnapshot):SelectionInput[] {
 return value.selections.filter(item=>['style','writing_rule','expression_rule'].includes(item.kind)).map(item=>({origin:item.origin,resource_id:item.resource_id,...(item.personal_override?{personal_override:true,body:item.body}:{})}))
}
</script>
<template>
 <AdminDialog title="选择本书写作资源" contained :busy="props.busy" :on-close="()=>emit('close')">
  <div class="creation-resource-body">
  <p v-if="loading" role="status">正在加载本书已有资源…</p>
  <p v-else-if="loadError" role="alert">{{ loadError }} <button class="btn" @click="loadSnapshot">重试</button></p>
  <UserResourceCatalog v-else mode="choose" contained :initial-selection="snapshot ? editableSelections(snapshot) : undefined" :current-resources="snapshot?.selections" :preselected-style="preselectedStyle" @update:selection="selections=$event" @ready="ready=$event" />
  </div>
  <p v-if="error" role="alert">{{ error }}</p>
  <WaitingStatus v-if="busy" label="正在创建作品并保存写作资源" />
  <footer class="creation-resource-actions">
   <button class="btn" :disabled="busy" @click="emit('close')">返回方案</button>
   <button class="btn btn-primary" :disabled="busy||loading||!!loadError||!ready" @click="emit('confirm',selections)">{{ busy?'正在创建…':'确认资源并创建作品' }}</button>
  </footer>
 </AdminDialog>
</template>
<style scoped>
.creation-resource-actions {display:flex;justify-content:flex-end;flex-wrap:wrap;gap:12px;flex-shrink:0;background:var(--surface-1);padding:16px 0;margin-top:16px;}
.creation-resource-body {min-height:0;overflow-y:auto;overscroll-behavior:contain;scrollbar-gutter:stable;}
</style>
