import { h } from 'vue'
import { afterEach, expect, it } from 'vitest'
import { cleanup, render, screen } from '../workspaceTestUtils'
import CandidatePanel from './CandidatePanel.vue'
import RingProgress from './RingProgress.vue'
afterEach(cleanup)
it('sizes the progress ring in pixels and clamps its percentage', () => {
 render(h(RingProgress,{value:2,ariaLabel:'进度',label:'成稿',size:148}))
 const ring=screen.getByRole('progressbar')
 expect(ring.style.width).toBe('148px')
 expect(ring.getAttribute('aria-valuenow')).toBe('100')
})
it('focuses the confirmation dialog on its initial mount', () => {
 render(h(CandidatePanel,{projectId:'p',candidates:[{candidate_id:'c',kind:'fact',source_chapter:1,payload:{content:'设定'},confidence:1,status:'pending',created_at:null}],onChanged:()=>{}}))
 expect(document.activeElement).toBe(screen.getByRole('button',{name:'暂后处理'}))
})
