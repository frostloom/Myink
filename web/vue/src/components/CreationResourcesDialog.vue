<script setup lang="ts">
import { ref } from 'vue'
import WaitingStatus from './WaitingStatus.vue'
import { AdminDialog } from '../pages/admin/AdminDialog'
import UserResourceCatalog from './UserResourceCatalog.vue'
import type { SelectionInput } from '../../../src/lib/writingResources'
const props = defineProps<{busy: boolean; error?: string | null}>()
const emit = defineEmits<{confirm: [SelectionInput[]]; close: []}>()
const ready = ref(false)
const selections = ref<SelectionInput[]>([])
</script>
<template>
 <AdminDialog title="选择本书写作资源" contained :busy="props.busy" :on-close="()=>emit('close')">
  <div class="creation-resource-body">
  <UserResourceCatalog mode="choose" contained @update:selection="selections=$event" @ready="ready=$event" />
  </div>
  <p v-if="error" role="alert">{{ error }}</p>
  <WaitingStatus v-if="busy" label="正在创建作品并保存写作资源" />
  <footer class="creation-resource-actions">
   <button class="btn" :disabled="busy" @click="emit('close')">返回方案</button>
   <button class="btn btn-primary" :disabled="busy||!ready" @click="emit('confirm',selections)">{{ busy?'正在创建…':'确认资源并创建作品' }}</button>
  </footer>
 </AdminDialog>
</template>
<style scoped>
.creation-resource-actions {display:flex;justify-content:flex-end;flex-wrap:wrap;gap:12px;flex-shrink:0;background:var(--surface-1);padding:16px 0;margin-top:16px;}
.creation-resource-body {min-height:0;overflow-y:auto;overscroll-behavior:contain;scrollbar-gutter:stable;}
</style>
