import { cleanup, render, screen } from '@testing-library/vue'
import { afterEach, expect, it, vi } from 'vitest'
import CreationResourcesDialog from './CreationResourcesDialog.vue'
const api = vi.hoisted(() => ({ snapshot: vi.fn(), catalogAll: vi.fn(), personal: vi.fn() }))
vi.mock('../../../src/lib/writingResources', async original => ({ ...await original<object>(), writingResources: api }))
afterEach(cleanup)
it('loads the existing frozen book style and default rules before confirming', async () => {
 const style = {resource_id:'style',origin:'platform',name:'书中风格',kind:'style',version:1,generation:1,body:{profile:{narrative_voice:'冻结声音'}},personal_override:false,authoritative_style:true}
 const rule = {resource_id:'rule',origin:'platform',name:'默认规则',kind:'writing_rule',version:1,generation:1,body:{roles:{writer:'规则'}},personal_override:false}
 api.snapshot.mockResolvedValue({revision:2,configured:true,selections:[style,rule]})
 api.catalogAll.mockResolvedValue({items:[]});api.personal.mockResolvedValue({items:[]})
 render(CreationResourcesDialog,{props:{busy:false,projectId:'book'}})
 expect((await screen.findByRole('checkbox',{name:'选用 书中风格'}) as HTMLInputElement).checked).toBe(true)
 expect((screen.getByRole('checkbox',{name:'选用 默认规则'}) as HTMLInputElement).checked).toBe(true)
 expect(api.snapshot).toHaveBeenCalledWith('book')
})
