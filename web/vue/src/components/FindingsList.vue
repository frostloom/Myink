<script setup lang="ts">
import { computed } from 'vue';
import { conflictTypeLabel, findingSourceLabel, severityLabel, severityTone } from '../../../src/lib/labels';
import type { Finding, FindingSeverity } from '../../../src/types';
import StatusBadge from './StatusBadge.vue';
import styles from '../../../src/components/FindingsList.module.css';
const props = defineProps<{
    findings: Finding[];
    onNavigateChapter?: (seq: number) => void;
}>();
const order: FindingSeverity[] = ['critical', 'major', 'minor', 'hint'];
const sorted = computed(() => [...props.findings].sort((a, b) => order.indexOf(a.severity) - order.indexOf(b.severity)));
</script>
<template><p v-if="!sorted.length" class="empty">未发现冲突。</p><ul v-else :class="styles.findings"><li v-for="f in sorted" :key="f.conflict_key" :class="styles.finding"><div :class="styles.findingHead"><StatusBadge :tone="severityTone(f.severity)">{{ severityLabel(f.severity) }}</StatusBadge><span :class="styles.findingType">{{ conflictTypeLabel(f.conflict_type) }}</span><span :class="styles.findingType">{{ f.scope==='local'?'局部':f.scope==='structural'?'结构':'范围未定' }}</span></div><p :class="styles.findingSrc">{{ findingSourceLabel(f.source) }}</p><blockquote v-for="(ev,i) in f.evidence" :key="i" :class="styles.evidence"><button v-if="onNavigateChapter" type="button" :class="styles.chapter" @click="onNavigateChapter(ev.chapter)">第 {{ ev.chapter }} 章 →</button><span v-else :class="styles.chapterText">第 {{ ev.chapter }} 章</span><span :class="styles.quote">{{ ev.quote }}</span></blockquote><p v-if="f.suggestion" :class="styles.suggestion">建议：{{ f.suggestion }}</p></li></ul></template>
