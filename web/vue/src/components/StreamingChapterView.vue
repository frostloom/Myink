<script setup lang="ts">
import {computed,ref,watch,nextTick,onMounted} from 'vue'
import type {ArtifactState} from '../composables/useTaskEvents'
import styles from '../../../src/components/StreamingChapterView.module.css'
const props=defineProps<{chapterSeq:number;artifact:ArtifactState|null;summary?:string|null}>()
const source=computed(()=>{const text=props.artifact?.content??'',leading=text.trimStart(),marker='=== CONTENT ===';return leading.length<marker.length&&marker.startsWith(leading.toUpperCase())?'':text.replace(/^\s*===\s*CONTENT\s*===\s*/i,'')})
const label=computed(()=>!props.artifact?'连接 Writer':props.artifact.failed?'生成重试中':props.artifact.complete?'写作完成':'实时写作')
const paper=ref<HTMLDivElement|null>(null),following=ref(true)
function latest(){following.value=true;if(paper.value)paper.value.scrollTop=paper.value.scrollHeight}
function scroll(){if(paper.value)following.value=paper.value.scrollHeight-paper.value.scrollTop-paper.value.clientHeight<=80}
watch([()=>props.chapterSeq,()=>props.artifact?.artifactId],()=>{following.value=true})
onMounted(()=>{if(source.value)latest()})
watch(source,()=>{void nextTick(()=>{if(following.value)latest()})})
</script>
<template><section :class="styles.wrap" :aria-label="`第 ${chapterSeq} 章生成正文`"><header :class="styles.head"><div><h2>第 {{ chapterSeq }} 章</h2><p>{{ summary?.trim()||(!artifact?'Plan 已确认，正在连接 Writer。':'正文生成中；本章摘要将在内容检查后显示。') }}</p></div><span :class="styles.status">{{ label }}<i aria-hidden="true" /></span></header><div ref="paper" :class="styles.paper" role="region" aria-label="正文实时预览" aria-live="polite" @scroll="scroll"><pre v-if="source">{{ source }}<span v-if="!artifact?.complete" :class="styles.cursor" aria-hidden="true" /></pre><div v-else :class="styles.waiting">{{ !artifact?'Writer 正在连接模型…':'模型已开始响应，正在等待第一段正文…' }}</div><button v-if="!following&&!artifact?.complete" type="button" :class="styles.followButton" @click="latest">回到最新</button></div><footer>{{ Array.from(source).length.toLocaleString() }} 字</footer></section></template>
