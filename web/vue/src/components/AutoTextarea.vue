<script setup lang="ts">
import { ref,onMounted,onScopeDispose,watch,nextTick } from 'vue'
import { resizeTextarea } from '../../../src/lib/resizeTextarea'
const props=defineProps<{value?:string|number;onChange?:(event:Event)=>void;onInput?:(event:Event)=>void}>()
const element=ref<HTMLTextAreaElement|null>(null)
let observer:ResizeObserver|null=null
function resize(){if(element.value)resizeTextarea(element.value)}
function input(event:Event){resize();props.onInput?.(event);props.onChange?.(event)}
onMounted(()=>{resize();if(typeof ResizeObserver!=='undefined'&&element.value){observer=new ResizeObserver(resize);observer.observe(element.value)}})
watch(()=>props.value,()=>{void nextTick(resize)})
onScopeDispose(()=>observer?.disconnect())
</script>
<template><textarea ref="element" :value="value" style="overflow-y:hidden;resize:none" @input="input" /></template>
