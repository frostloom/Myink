import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/vue'
import ConnectionNotices from './ConnectionNotices.vue'
afterEach(cleanup)
it('scrolls new results into view and restores the connected trigger on Escape', async () => {
 const trigger = document.createElement('button'); document.body.append(trigger); trigger.focus(); const dismiss = vi.fn()
 const item = { id: 'a', tone: 'error' as const, text: '旧错误', returnFocus: trigger }
 const view = render(ConnectionNotices, { props: { items: [item], onDismiss: dismiss } })
 const region = screen.getByRole('region', { name: '模型连接通知' }); region.scrollTop = 200
 await view.rerender({ items: [{ ...item, text: '新错误' }] }); expect(region.scrollTop).toBe(0); expect(document.activeElement).toBe(trigger)
 await fireEvent.keyDown(screen.getByRole('button', {name:'关闭通知'}), {key:'Escape'}); expect(dismiss).toHaveBeenCalledWith('a'); expect(document.activeElement).toBe(trigger); trigger.remove()
})
