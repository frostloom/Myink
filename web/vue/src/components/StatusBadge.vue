<script setup lang="ts">
export type BadgeTone = 'critical' | 'major' | 'minor' | 'hint' | 'success' | 'warning' | 'error' | 'accent';
defineProps<{
    tone: BadgeTone;
}>();
</script>
<template><span :class="`badge badge-${tone}`"><slot /></span></template>
