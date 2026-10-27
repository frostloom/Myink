<script setup lang="ts">
defineProps<{ label: string }>()
</script>
<template>
 <div class="waiting-status" role="status" :aria-label="label" aria-live="polite">
  <progress :aria-label="label" />
  <span>{{ label }}，请稍候…</span>
 </div>
</template>
<style scoped>
.waiting-status { display:flex; align-items:center; gap:10px; padding:10px 0; color:var(--ink-muted); font-size:var(--text-small); overflow-wrap:anywhere; }
progress { width:48px; height:6px; flex-shrink:0; accent-color:var(--accent); }
</style>
