import { render, screen, cleanup, fireEvent } from '@testing-library/vue'
import { afterEach, expect, it, vi } from 'vitest'
import NativeDialog from './NativeDialog.vue'
afterEach(cleanup)
it('opens in the native modal layer and restores focus to its trigger', async () => {
 const trigger=document.createElement('button');document.body.append(trigger);trigger.focus()
 const modal=vi.fn(function(this:HTMLDialogElement){this.setAttribute('open','')})
 Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value:modal})
 const close=vi.fn()
 const view=render(NativeDialog,{props:{onClose:close},attrs:{'aria-label':'预览'},slots:{default:'<button>关闭</button>'}})
 expect(modal).toHaveBeenCalledOnce()
 await fireEvent(screen.getByRole('dialog',{name:'预览'}),new Event('cancel',{cancelable:true}))
 expect(close).toHaveBeenCalledOnce()
 view.unmount();expect(document.activeElement).toBe(trigger);trigger.remove();Reflect.deleteProperty(HTMLDialogElement.prototype,'showModal')
})
it('closes on a backdrop click but not a click or drag from dialog content', async () => {
 const close=vi.fn();render(NativeDialog,{props:{onClose:close},attrs:{'aria-label':'预览'}})
 const dialog=screen.getByRole('dialog',{name:'预览'})
 vi.spyOn(dialog,'getBoundingClientRect').mockReturnValue({left:100,top:100,right:500,bottom:500} as DOMRect)
 await fireEvent(dialog,new MouseEvent('pointerdown',{clientX:150,clientY:150,bubbles:true}))
 await fireEvent.click(dialog,{clientX:10,clientY:10})
 expect(close).not.toHaveBeenCalled()
 await fireEvent(dialog,new MouseEvent('pointerdown',{clientX:10,clientY:10,bubbles:true}))
 await fireEvent.click(dialog,{clientX:10,clientY:10})
 expect(close).toHaveBeenCalledOnce()
})
it('wraps Tab and Shift+Tab between dialog actions', async () => {
 render(NativeDialog,{props:{onClose:vi.fn()},attrs:{'aria-label':'键盘'},slots:{default:'<button>首个</button><button disabled>禁用</button><button>末个</button>'}})
 const first=screen.getByRole('button',{name:'首个'}),last=screen.getByRole('button',{name:'末个'})
 last.focus();await fireEvent.keyDown(last,{key:'Tab'});expect(document.activeElement).toBe(first)
 await fireEvent.keyDown(first,{key:'Tab',shiftKey:true});expect(document.activeElement).toBe(last)
})
