import { afterEach, expect, it, vi } from 'vitest'
import { render,fireEvent,screen,cleanup } from '@testing-library/vue'
import { defineComponent,ref,h } from 'vue'
import StructuredTextField from './StructuredTextField.vue'
import GenrePackFields from './GenrePackFields.vue'
import AutoTextarea from './AutoTextarea.vue'
import { emptyFields } from '../../../src/lib/genrePacks'
afterEach(cleanup)
it('retains editable trailing blank lines while emitting parsed lists',async()=>{
 const Host=defineComponent({setup(){const value=ref(['first']);return()=>h('div',[h(StructuredTextField<string[]>,{value:value.value,format:(v:string[])=>v.join('\n'),parse:(v:string)=>v.split('\n').filter(Boolean),onChange:(next:string[])=>{value.value=next},'aria-label':'目标'}),h('output',String(value.value.length))])}})
 render(Host);const field=screen.getByRole('textbox',{name:'目标'});await fireEvent.update(field,'first\nsecond\n');expect((field as HTMLTextAreaElement).value).toBe('first\nsecond\n');expect(screen.getByRole('status').textContent).toBe('2')
})
it('updates genre subgenres and preserves unknown extra fields',async()=>{
 const changed=vi.fn();render(GenrePackFields,{props:{value:{...emptyFields(),selling_point:'old'},onChange:changed}});await fireEvent.update(screen.getByLabelText('流派提示（每行「名称｜钩子」）'),'玄幻|逆袭');expect(changed).toHaveBeenCalledWith({...emptyFields(),selling_point:'old',subgenres:[{name:'玄幻',hook:'逆袭'}]})
})

it('resizes textarea on input instead of trapping a nested scrollbar',async()=>{const descriptor=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'scrollHeight');Object.defineProperty(HTMLTextAreaElement.prototype,'scrollHeight',{configurable:true,get:()=>120});try{render(AutoTextarea, {attrs:{'aria-label':'自动正文'}});const field=screen.getByRole('textbox');await fireEvent.input(field);expect((field as HTMLTextAreaElement).style.height).toBe('120px')}finally{if(descriptor)Object.defineProperty(HTMLTextAreaElement.prototype,'scrollHeight',descriptor);else delete (HTMLTextAreaElement.prototype as unknown as Record<string,unknown>).scrollHeight}})

it('resets incomplete raw object lines when an equivalent external object replaces the value',async()=>{
 const Host=defineComponent({setup(){const value=ref<Record<string,string>>({魔法:'有代价'});return()=>h('div',[h(StructuredTextField<Record<string,string>>,{value:value.value,format:rules=>Object.entries(rules).map(([k,v])=>`${k}：${v}`).join('\n'),parse:text=>Object.fromEntries(text.split('\n').filter(line=>line.includes('：')).map(line=>line.split('：'))),onChange:next=>{value.value=next}}),h('button',{onClick:()=>{value.value={魔法:'有代价'}}},'替换规则')])}})
 render(Host);const field=screen.getByRole('textbox') as HTMLTextAreaElement;await fireEvent.update(field,'魔法：有代价\n未完成');expect(field.value).toBe('魔法：有代价\n未完成');await fireEvent.click(screen.getByRole('button',{name:'替换规则'}));expect(field.value).toBe('魔法：有代价')
})
it('resets trailing single-line delimiters when a new equivalent plan replaces participants',async()=>{
 const Host=defineComponent({setup(){const value=ref(['林尘']);return()=>h('div',[h(StructuredTextField<string[]>,{singleLine:true,value:value.value,format:people=>people.join('、'),parse:text=>text.split('、').filter(Boolean),onChange:next=>{value.value=next}}),h('button',{onClick:()=>{value.value=['林尘']}},'替换人物')])}})
 render(Host);const field=screen.getByRole('textbox') as HTMLInputElement;await fireEvent.update(field,'林尘、');expect(field.value).toBe('林尘、');await fireEvent.click(screen.getByRole('button',{name:'替换人物'}));expect(field.value).toBe('林尘')
})
