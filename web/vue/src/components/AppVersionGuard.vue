<script setup lang="ts">
import { onMounted, onScopeDispose, ref } from 'vue'
import { hasPendingWrites, subscribePendingWrites } from '../../../src/lib/pendingWrites'
import { requestReleaseRefresh, watchRelease } from '../../../src/lib/release'
const available = ref(false)
const pending = ref(hasPendingWrites())
let stop = () => {}
const unsubscribe = subscribePendingWrites(() => { pending.value = hasPendingWrites() })
onMounted(() => { stop = watchRelease(() => { available.value = true }) })
onScopeDispose(() => { stop(); unsubscribe() })
function refresh() { requestReleaseRefresh(hasPendingWrites, message => window.confirm(message), () => window.location.reload()) }
</script>
<template><div v-if="available" class="banner" role="status" data-guest-exempt>新版本已就绪。请先保存当前内容，再刷新页面。<button type="button" class="btn btn-quiet" :disabled="pending" @click="refresh">刷新到新版本</button><span v-if="pending">正在保存，请等待完成。</span></div></template>
