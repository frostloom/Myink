<script setup lang="ts" generic="T">
import { ref,toRaw,watch } from 'vue'
const props=withDefaults(defineProps<{value:T;format:(value:T)=>string;parse:(text:string)=>T;onChange?:(value:T)=>void;singleLine?:boolean;rows?:number;className?:string}>(),{singleLine:false,onChange:undefined,rows:undefined,className:undefined})
const text=ref(props.format(props.value))
let lastEmitted=toRaw(props.value)
watch(()=>[props.value,props.format(props.value)] as const,([value,formatted])=>{if(toRaw(value)!==lastEmitted){lastEmitted=toRaw(value);text.value=formatted}})
function edit(event:Event){const nextText=(event.target as HTMLInputElement).value;const next=props.parse(nextText);lastEmitted=toRaw(next);text.value=nextText;props.onChange?.(next)}
</script>
<template><input v-if="singleLine" :value="text" :class="['input',className]" @input="edit" /><textarea v-else :value="text" :class="['textarea',className]" :rows="rows" @input="edit" /></template>
