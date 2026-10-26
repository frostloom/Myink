<script setup lang="ts">
import { onErrorCaptured, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
const route = useRoute()
const failed = ref(false)
onErrorCaptured(() => { failed.value = true; return false })
watch(() => route.fullPath, () => { failed.value = false })
function reload() { window.location.reload() }
</script>
<template>
  <div v-if="failed" class="empty" role="alert" data-guest-exempt><p>页面出错了，请刷新重试。</p><button type="button" class="btn btn-primary" @click="reload">刷新页面</button> <RouterLink to="/" class="btn btn-quiet">回到首页</RouterLink></div>
  <slot v-else />
</template>
