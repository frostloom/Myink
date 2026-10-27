<script setup lang="ts">
import {computed,onScopeDispose,ref,watch} from 'vue'
import {useRoute,useRouter} from 'vue-router'
import {api} from '../../../src/lib/api'
import {formatApiError} from '../../../src/lib/apiError'
const route=useRoute(),router=useRouter()
const projectId=computed(()=>String(route.params.projectId??''))
const error=ref('')
let serial=0
async function load(){
 const request=++serial,pid=projectId.value;error.value=''
 try{
  const books=await api.listProjects();if(request!==serial)return
  const book=books.find(item=>item.id===pid)
  if(!book)throw new Error('作品不存在或无权查看')
  await router.replace({path:`/projects/${pid}${book.form==='short'?'':'/settings'}`,state:{planWarning:router.options.history.state.planWarning}})
 }catch(cause){if(request===serial)error.value=formatApiError(cause,'作品加载失败')}
}
watch(projectId,()=>void load(),{immediate:true})
onScopeDispose(()=>{serial++})
</script>
<template><main class="empty"><div v-if="error" role="alert">{{ error }} <button class="btn" @click="load">重新加载</button></div><p v-else role="status">正在打开作品…</p></main></template>
