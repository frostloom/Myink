import { render, cleanup } from '@testing-library/vue'
import { afterEach, expect, it } from 'vitest'
import PendantLamp from './PendantLamp.vue'
afterEach(cleanup)
it('uses CSS lengths for the hanging fixture dimensions',()=>{
 const {container}=render(PendantLamp,{props:{id:'cube',lit:true,hanging:true}})
 const svg=container.querySelector('svg')!
 expect(svg.style.width).toBe('104px')
 expect(svg.style.height).toMatch(/px$/)
})
it('updates the lit SVG paint when lamp props change',async()=>{
 const {container,rerender}=render(PendantLamp,{props:{id:'cube',lit:true}})
 expect(container.innerHTML).toContain('#fff6df')
 await rerender({id:'cube',lit:false})
 expect(container.innerHTML).toContain('#e7dcc8')
})
