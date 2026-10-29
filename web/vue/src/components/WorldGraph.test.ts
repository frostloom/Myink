import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/vue'
import { api } from '../../../src/lib/api'
import WorldGraph from './WorldGraph.vue'
const chart=vi.hoisted(()=>({setOption:vi.fn(),resize:vi.fn(),dispose:vi.fn()}))
vi.mock('echarts/core',()=>({use:vi.fn(),init:()=>chart}))
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.unstubAllGlobals();vi.clearAllMocks()})
it('renders graph data and disposes resize and chart resources',async()=>{const disconnect=vi.fn();vi.stubGlobal('ResizeObserver',class {observe(){}disconnect=disconnect});vi.spyOn(api,'listGraph').mockResolvedValue({nodes:[{id:'a',name:'人物',category:'character'}],edges:[]} as never);const view=render(WorldGraph,{props:{projectId:'p'}});await vi.waitFor(()=>expect(chart.setOption).toHaveBeenCalledOnce());view.unmount();expect(chart.dispose).toHaveBeenCalledOnce();expect(disconnect).toHaveBeenCalledOnce()})
it('shows empty graph and ignores old responses on project switch',async()=>{vi.stubGlobal('ResizeObserver',class{observe(){}disconnect(){}});let finish!:(g:{nodes:never[];edges:never[]})=>void;vi.spyOn(api,'listGraph').mockImplementation(id=>id==='a'?new Promise(resolve=>{finish=resolve}):Promise.resolve({nodes:[],edges:[]}));const view=render(WorldGraph,{props:{projectId:'a'}});await view.rerender({projectId:'b'});expect(await screen.findByText(/暂无关系与设定数据/)).toBeTruthy();finish({nodes:[],edges:[]});expect(chart.setOption).not.toHaveBeenCalled()})
