import { render, screen, fireEvent, cleanup } from '@testing-library/vue'
import { afterEach, expect, it, vi } from 'vitest'
import AttachmentChip from './AttachmentChip.vue'
import { fetchFeedbackAttachment } from '../../../src/lib/api'
vi.mock('../../../src/lib/api',()=>({fetchFeedbackAttachment:vi.fn(async()=>new Blob(['x']))}))
afterEach(()=>{cleanup();vi.unstubAllGlobals()})
it('fetches attachment bytes through the authenticated API after opening a tab',async()=>{ const tab={closed:false,opener:{},location:{href:''},close:vi.fn()}; vi.spyOn(window,'open').mockReturnValue(tab as unknown as Window); vi.stubGlobal('URL',{createObjectURL:vi.fn(()=> 'blob:attachment'),revokeObjectURL:vi.fn()});render(AttachmentChip,{props:{feedbackId:'f',attachment:{index:2,name:'capture.png',mime:'image/png',bytes:12}}});await fireEvent.click(screen.getByRole('button',{name:/capture.png/}));expect(fetchFeedbackAttachment).toHaveBeenCalledWith('f',2,expect.any(AbortSignal));expect(tab.location.href).toBe('blob:attachment');expect(tab.opener).toBeNull()})
