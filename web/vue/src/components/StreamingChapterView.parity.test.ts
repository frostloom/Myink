import { cleanup, fireEvent, render, screen } from '@testing-library/vue'
import { nextTick } from 'vue'
import { afterEach, expect, it } from 'vitest'
import type { ArtifactState } from '../composables/useTaskEvents'
import StreamingChapterView from './StreamingChapterView.vue'
afterEach(cleanup)
function artifact(content: string): ArtifactState { return { artifactId:'w',taskId:'t',stage:'write',chapterSeq:8,attempt:1,content,complete:false,failed:false,artifact:null,message:null } }
it('shows incomplete fragments and updates without waiting for completion', async () => { const view=render(StreamingChapterView,{props:{chapterSeq:8,artifact:artifact('=== CONTENT ===\n第一段')}});expect(screen.getByText('第一段')).toBeTruthy();expect(screen.getByText('实时写作')).toBeTruthy();await view.rerender({artifact:artifact('=== CONTENT ===\n第二段')});expect(screen.getByText('第二段')).toBeTruthy() })
it('hides incomplete protocol markers',()=>{render(StreamingChapterView,{props:{chapterSeq:8,artifact:artifact('=== CONT')}});expect(screen.queryByText('=== CONT')).toBeNull();expect(screen.getByText('模型已开始响应，正在等待第一段正文…')).toBeTruthy()})
it('retains the chapter summary when rewriting',()=>{render(StreamingChapterView,{props:{chapterSeq:8,artifact:artifact('新的正文'),summary:'旧章摘要'}});expect(screen.getByText('旧章摘要')).toBeTruthy();expect(screen.getByText('新的正文')).toBeTruthy()})
async function stream(){const view=render(StreamingChapterView,{props:{chapterSeq:8,artifact:artifact('第一段')}});const paper=screen.getByRole('region',{name:'正文实时预览'});Object.defineProperty(paper,'scrollHeight',{configurable:true,value:900});Object.defineProperty(paper,'clientHeight',{configurable:true,value:300});return {view,paper}}
it('follows new text near the bottom',async()=>{const {view,paper}=await stream();await view.rerender({artifact:artifact('第一段\n第二段')});await nextTick();expect(paper.scrollTop).toBe(900)})
it('pauses after scrolling up and resumes on request',async()=>{const {view,paper}=await stream();paper.scrollTop=120;await fireEvent.scroll(paper);await view.rerender({artifact:artifact('第一段\n第二段')});await nextTick();expect(paper.scrollTop).toBe(120);await fireEvent.click(screen.getByRole('button',{name:'回到最新'}));expect(paper.scrollTop).toBe(900)})
