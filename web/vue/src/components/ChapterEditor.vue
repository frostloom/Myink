<script setup lang="ts">
import {ref,computed,watch,onScopeDispose} from 'vue'
import {useRouter} from 'vue-router'
import type {ChapterMeta} from '../../../src/types'
import {api} from '../../../src/lib/api'
import {getSession} from '../../../src/lib/token'
import {formatApiError} from '../../../src/lib/apiError'
import {chapterStatusLabel,chapterStatusTone} from '../../../src/lib/labels'
import {useChapterDraft} from '../composables/useChapterDraft'
import StatusBadge from './StatusBadge.vue'
import VersionHistory from './VersionHistory.vue'
import styles from '../../../src/components/ChapterEditor.module.css'
const props=withDefaults(defineProps<{projectId:string;chapter:ChapterMeta;refreshTick?:number;allowMemoryCorrection?:boolean}>(),{refreshTick:0,allowMemoryCorrection:true})
const emit=defineEmits<{notFound:[];saved:[];memoryChanged:[]}>()
const restoreTick=ref(0),showHistory=ref(false),actionError=ref<string|null>(null),memoryBusy=ref(false),deleteBusy=ref(false),memoryBanner=ref<string|null>(null)
let alive=true,epoch=0
watch(()=>[props.projectId,props.chapter.id],()=>{epoch++;showHistory.value=false;actionError.value=null;memoryBanner.value=null;memoryBusy.value=false;deleteBusy.value=false})
onScopeDispose(()=>{alive=false;epoch++})
const key=computed(()=>`myink.draft:${getSession()?.userId??'anonymous'}:${props.projectId}:${props.chapter.id}`)
const editor=useChapterDraft({key,projectId:()=>props.projectId,chapterId:()=>props.chapter.id,refreshTick:()=>props.refreshTick+restoreTick.value,onNotFound:()=>emit('notFound'),onSaved:()=>emit('saved'),router:useRouter()})
function keydown(event:KeyboardEvent){if((event.ctrlKey||event.metaKey)&&event.key==='s'){event.preventDefault();if(editor.dirty&&!editor.conflict&&!showHistory.value)void editor.save()}}
async function correct(){if(memoryBusy.value||editor.dirty||editor.saving)return;const version=epoch;memoryBusy.value=true;actionError.value=null;memoryBanner.value=null;try{const response=await api.correctMemory(props.projectId,props.chapter.id);if(alive&&version===epoch){memoryBanner.value=response.no_op?'无记忆变更（正文与已落库记忆一致）。':'已生成变更集，进入「待确认候选」池。';emit('memoryChanged')}}catch(err){if(alive&&version===epoch)actionError.value=formatApiError(err,'校正失败')}finally{if(alive&&version===epoch)memoryBusy.value=false}}
async function remove(){if(deleteBusy.value||!window.confirm(`删除第 ${props.chapter.chapter_seq} 章及其后全部章节？正文、记忆与待确认候选将一并移除，不可撤销。`))return;const version=epoch;deleteBusy.value=true;actionError.value=null;try{await api.deleteChapter(props.projectId,props.chapter.id);if(alive&&version===epoch)emit('notFound')}catch(err){if(alive&&version===epoch)actionError.value=formatApiError(err,'删除失败')}finally{if(alive&&version===epoch)deleteBusy.value=false}}
function overwrite(){if(editor.detail&&window.confirm('确认将当前草稿保存为新版本？服务器当前正文会保留在历史版本中。'))void editor.save(editor.detail.version)}
function restored(){showHistory.value=false;emit('saved');restoreTick.value++}
</script>
<template>
<div :class="styles.editor">
<header :class="styles.head"><div :class="styles.headRow"><h2 :class="styles.title">第 {{ chapter.chapter_seq }} 章{{ editor.detail?.title?` · ${editor.detail.title}`:'' }}</h2><div v-if="editor.detail" :class="styles.actions"><button v-if="allowMemoryCorrection" type="button" class="btn btn-quiet" :disabled="memoryBusy||deleteBusy||editor.dirty||editor.saving" @click="correct">{{ memoryBusy?'校正中…':'校正记忆' }}</button><button type="button" :class="['btn',styles.danger]" :disabled="memoryBusy||deleteBusy||editor.saving" @click="remove">{{ deleteBusy?'删除中…':'删除本章' }}</button><button type="button" class="btn btn-quiet" :disabled="editor.dirty||editor.saving" @click="showHistory=true">历史版本</button></div></div><div :class="styles.metaRow"><StatusBadge :tone="chapterStatusTone(chapter.status)">{{ chapterStatusLabel(chapter.status) }}</StatusBadge><span v-if="editor.draft" :class="styles.version">v{{ editor.draft.baseVersion }}</span><span v-if="editor.detail?.summary" :class="styles.summary">{{ editor.detail.summary }}</span></div></header>
<div v-if="actionError||editor.error" role="alert" class="banner banner-error">{{ actionError||editor.error }}</div><div v-if="editor.backupError" role="alert" class="banner banner-error">浏览器草稿备份失败，请立即保存或复制正文，勿关闭页面。</div>
<div v-if="editor.conflict&&editor.detail" class="banner">服务器已有 v{{ editor.detail.version }}，当前草稿基于 v{{ editor.draft?.baseVersion }}。请比较后处理。<details><summary>查看服务器正文</summary><pre style="white-space:pre-wrap">{{ editor.detail.content }}</pre></details><button type="button" class="btn btn-quiet" :disabled="editor.saving" @click="overwrite">以当前草稿保存为新版本</button><button type="button" class="btn btn-quiet" :disabled="editor.saving" @click="editor.acceptRemote">放弃草稿，载入服务器版本</button></div><div v-if="memoryBanner" class="banner">{{ memoryBanner }}</div>
<div v-if="!editor.detail||!editor.draft" class="empty">{{ editor.error?'正文暂不可用':'加载中…' }}</div><template v-else><textarea :class="styles.textarea" aria-label="章节正文" :value="editor.draft.content" :readonly="showHistory||memoryBusy||deleteBusy" :spellcheck="false" placeholder="章节正文…（Ctrl+S 保存）" @input="editor.edit(($event.target as HTMLTextAreaElement).value)" @keydown="keydown" /><footer :class="styles.foot"><span :class="editor.dirty?styles.dirty:styles.saved">{{ editor.dirty?(editor.backupError?'未保存修改':'草稿已备份到本标签页，尚未提交'):'已保存' }}</span><button type="button" class="btn btn-primary" :disabled="!editor.dirty||editor.saving||editor.conflict||showHistory" @click="editor.save()">{{ editor.saving?'保存中…':'保存' }}</button></footer></template><VersionHistory v-if="showHistory" :project-id="projectId" :chapter-id="chapter.id" :chapter-seq="chapter.chapter_seq" @close="showHistory=false" @restored="restored" />
</div>
</template>
