<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue'
const props = defineProps<{onClose: () => void}>()
const element = ref<HTMLDialogElement | null>(null)
let previous: HTMLElement | null = null
let beganOutside = false
function outside(event: MouseEvent) {
 const dialog = element.value
 if (!dialog || event.target !== dialog) return false
 const rect = dialog.getBoundingClientRect()
 return event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom
}
function keyboard(event: KeyboardEvent) {
 if (event.key !== 'Tab' || !element.value) return
 const controls = Array.from(element.value.querySelectorAll<HTMLElement>('button,a[href],input,select,textarea,summary,[contenteditable=true],[tabindex]'))
  .filter(el => el.tabIndex >= 0 && !el.matches(':disabled,input[type=hidden]') && !el.closest('[hidden]') && getComputedStyle(el).display !== 'none' && getComputedStyle(el).visibility !== 'hidden')
 if (!controls.length) { event.preventDefault(); element.value.focus(); return }
 // WebKit may skip buttons under the OS keyboard preference; navigate every
 // Tab explicitly so all supported engines keep the same modal interaction.
 const current = controls.indexOf(document.activeElement as HTMLElement)
 const next = current < 0 ? (event.shiftKey ? controls.length - 1 : 0)
  : (current + (event.shiftKey ? -1 : 1) + controls.length) % controls.length
 event.preventDefault()
 controls[next]?.focus()
 // Firefox may leave a partially visible control clipped after programmatic
 // focus. Tab navigation must reveal the whole control in its scroll container.
 controls[next]?.scrollIntoView?.({ block: 'nearest', inline: 'nearest', behavior: 'instant' })
}
function backdrop(event: MouseEvent) {
 if (beganOutside && outside(event)) props.onClose()
 beganOutside = false
}
onMounted(() => {
 previous = document.activeElement as HTMLElement | null
 if (typeof element.value?.showModal === 'function') element.value.showModal()
 else element.value?.setAttribute('open', '')
 const initial = element.value?.querySelector<HTMLElement>('[autofocus],button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled)')
 ;(initial ?? element.value)?.focus({preventScroll:true})
})
onBeforeUnmount(() => {
 element.value?.close?.()
 if (previous?.isConnected) previous.focus({preventScroll:true})
})
</script>
<template><dialog ref="element" tabindex="-1" @keydown="keyboard" @cancel.prevent="props.onClose" @pointerdown="beganOutside=outside($event)" @click="backdrop"><slot /></dialog></template>

<style scoped>dialog { color: var(--ink); }</style>
