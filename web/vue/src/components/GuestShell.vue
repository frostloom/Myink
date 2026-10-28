<script setup lang="ts">
import { nextTick, onMounted, onScopeDispose, ref } from 'vue'
import GuestEntry from './GuestEntry.vue'
import NativeDialog from './NativeDialog.vue'
import { useRouter } from 'vue-router'
import styles from '../../../src/components/GuestPromptDialog.module.css'
const router = useRouter()
const open = ref(false)
const closeButton = ref<HTMLButtonElement | null>(null)
let previousFocus: HTMLElement | null = null
const interactive = 'a[href],button,input,select,textarea,label,summary,[role="button"],[role="tab"],[contenteditable="true"]'
function close() { open.value = false; previousFocus?.focus() }
function block(event: Event) {
  const target = event.target
  if (!(target instanceof Element) || target.closest('[data-guest-exempt]')) return
  if (event.type !== 'submit' && !target.closest(interactive)) return
  event.preventDefault(); event.stopPropagation()
  previousFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null
  open.value = true
  void nextTick(() => closeButton.value?.focus())
}
function key(event: KeyboardEvent) { if (open.value && event.key === 'Escape') { event.stopPropagation(); close() } }
function go(path: string) { close(); void router.push(path) }
onMounted(() => { document.addEventListener('click', block, true); document.addEventListener('submit', block, true); document.addEventListener('keydown', key) })
onScopeDispose(() => { document.removeEventListener('click', block, true); document.removeEventListener('submit', block, true); document.removeEventListener('keydown', key) })
</script>
<template>
  <slot />
  <Teleport to="body">
    <div v-if="open" :class="styles.backdrop" data-guest-exempt @mousedown.self="close">
      <NativeDialog :class="styles.dialog" :on-close="close" aria-labelledby="guest-prompt-title">
        <header :class="styles.head"><h2 id="guest-prompt-title">当前是未登录的浏览模式</h2><button ref="closeButton" type="button" :class="styles.close" aria-label="关闭" @click="close">×</button></header>
        <div :class="styles.body"><p>这里只能查看。注册或登录后，作品、环境配置与主题都可以修改。</p><div :class="styles.actions"><button type="button" class="btn btn-primary" @click="go('/login?mode=register')">注册</button><button type="button" class="btn btn-secondary" @click="go('/login')">登录</button></div><GuestEntry @entered="close" /></div>
      </NativeDialog>
    </div>
  </Teleport>
</template>
