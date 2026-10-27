<script setup lang="ts">
import { ref, watch, onScopeDispose } from 'vue'
import ProjectRail from '../components/ProjectRail.vue'
import UserResourceCatalog from '../components/UserResourceCatalog.vue'
import { api } from '../../../src/lib/api'
import { useAuth } from '../authContext'
import type { Project } from '../../../src/types'
import styles from '../../../src/pages/SettingsPage.module.css'
const {session,status}=useAuth()
const projects=ref<Project[]>([])
let serial=0
watch(()=>session.value?.userId,async()=>{
 const request=++serial;projects.value=[]
 if(status.value!=='authenticated')return
 try {const books=await api.listProjects();if(request===serial)projects.value=books}catch{/* The resource catalog has its own retry UI. */}
},{immediate:true})
onScopeDispose(()=>{serial++})
</script>
<template>
 <div :class="styles.wrap">
<ProjectRail :projects="projects" /><main :class="styles.main">
<div :class="styles.inner">
  <header :class="styles.header"><h1>写作资源</h1></header>
  <UserResourceCatalog v-if="status==='authenticated'" :key="session?.userId" mode="library" />
  <p v-else>登录后查看和编辑你的写作资源。</p>
 </div>
</main>
</div>
</template>
