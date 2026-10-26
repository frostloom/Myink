<script setup lang="ts">
import { ref, onScopeDispose } from 'vue'
import { fetchFeedbackAttachment } from '../../../src/lib/api'
import type { FeedbackAttachment } from '../../../src/types'
import styles from '../../../src/components/FeedbackWidget.module.css'
const props = defineProps<{ feedbackId: string; attachment: FeedbackAttachment }>()
const state = ref<'idle' | 'busy' | 'error'>('idle')
function formatSize(bytes: number) {
 if (bytes < 1024) return `${bytes} B`
 if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
 return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
let alive = true
let pending: { controller: AbortController; tab: Window } | null = null
function closePending() {
 const request = pending
 pending = null
 if (!request) return
 request.controller.abort()
 try {
  if (!request.tab.closed && ['', 'about:blank'].includes(request.tab.location.href)) request.tab.close()
 } catch { /* A user-navigated tab belongs to the user now. */ }
}
onScopeDispose(() => { alive = false; closePending() })
async function open() {
 if (!alive || state.value === 'busy') return
 const tab = window.open('', '_blank')
 if (!tab) { state.value = 'error'; return }
 const controller = new AbortController()
 pending = { controller, tab }
 state.value = 'busy'
 try {
  const blob = await fetchFeedbackAttachment(props.feedbackId, props.attachment.index, controller.signal)
  if (!alive || controller.signal.aborted || pending?.controller !== controller) return
  pending = null
  if (tab.closed) { state.value = 'idle'; return }
  const url = URL.createObjectURL(blob)
  tab.opener = null
  tab.location.href = url
  // A completed tab may still be reading the media when this UI is disposed.
  window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
  state.value = 'idle'
 } catch {
  if (pending?.controller === controller) closePending()
  if (alive) state.value = 'error'
 }
}

</script>
<template><button type="button" :class="styles.chip" :disabled="state === 'busy'" @click="open"><span :class="styles.chipIcon" :data-video="attachment.mime.startsWith('video/') ? 'true' : undefined"><svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" focusable="false"><path v-if="attachment.mime.startsWith('video/')" d="M4 2.5h8a1.5 1.5 0 0 1 1.5 1.5v8a1.5 1.5 0 0 1-1.5 1.5H4A1.5 1.5 0 0 1 2.5 12V4A1.5 1.5 0 0 1 4 2.5Z M6.6 5.8l4 2.2-4 2.2Z" fill="currentColor" /><path v-else d="M3 2.5h10a.5.5 0 0 1 .5.5v10a.5.5 0 0 1-.5.5H3a.5.5 0 0 1-.5-.5V3a.5.5 0 0 1 .5-.5Zm2 7.2 2-2.4 2 2 1.4-1.6 1.6 1.9v.4H5Z" fill="currentColor" /></svg></span><span :class="styles.chipName">{{ attachment.name }}</span><span :class="styles.chipMeta">{{ state === 'error' ? '打开失败' : state === 'busy' ? '打开中…' : formatSize(attachment.bytes) }}</span></button></template>
