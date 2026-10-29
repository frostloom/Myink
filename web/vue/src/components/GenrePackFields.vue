<script setup lang="ts">
import type {GenreFields} from '../../../src/lib/genrePacks'
import StructuredTextField from './StructuredTextField.vue'
const props=defineProps<{value:GenreFields;onChange?:(value:GenreFields)=>void}>()
const lists={taboos:'禁忌（每行一条）',satisfaction:'爽点（每行一条）',mechanics:'机制/数值（每行一条）',world_hints:'世界观法则（每行一条）'} as const
const lines=(items:string[])=>items.join('\n')
const parse=(text:string)=>text.split('\n').map(s=>s.trim()).filter(Boolean)
const subgenreText=(value:GenreFields['subgenres'])=>value.map(s=>s.hook?`${s.name}｜${s.hook}`:s.name).join('\n')
const subgenreParse=(text:string)=>parse(text).map(line=>{const wide=line.indexOf('｜'),narrow=line.indexOf('|'),i=wide<0?narrow:narrow<0?wide:Math.min(wide,narrow);return i<=0?{name:line,hook:''}:{name:line.slice(0,i).trim(),hook:line.slice(i+1).trim()}})
function change<K extends keyof GenreFields>(key:K,value:GenreFields[K]){props.onChange?.({...props.value,[key]:value})}
</script>
<template>
<div>
<label class="field"><span>核心卖点</span><textarea class="textarea" rows="3" :value="value.selling_point" @input="change('selling_point',($event.target as HTMLTextAreaElement).value)" /></label>
<label class="field"><span>流派提示（每行「名称｜钩子」）</span><StructuredTextField :value="value.subgenres" :format="subgenreText" :parse="subgenreParse" :rows="Math.max(3,value.subgenres.length+1)" :on-change="next=>change('subgenres',next)" /></label>
<label class="field"><span>节奏</span><textarea class="textarea" rows="3" :value="value.pacing" @input="change('pacing',($event.target as HTMLTextAreaElement).value)" /></label>
<label v-for="(label,key) in lists" :key="key" class="field"><span>{{ label }}</span><StructuredTextField class="textarea" :value="value[key]" :format="lines" :parse="parse" :rows="Math.min(8,Math.max(3,value[key].length+1))" :on-change="next=>change(key,next)" /></label>
</div>
</template>

<style scoped>
.field{display:flex;flex-direction:column;gap:4px;margin-bottom:12px}
.field>span{font-size:.85rem;color:var(--ink-muted)}
</style>
