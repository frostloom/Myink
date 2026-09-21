// 未登录外壳：照常渲染页面（各页自己跳过需要凭据的请求），只在 document 捕获阶段
// 拦下所有控件交互，把动作换成一次「注册/登录」提示。
//
// 为什么用 capture + stopPropagation：React 19 把事件监听挂在 #root 容器上，
// document 是它的祖先，捕获阶段先在 document 触发；stopPropagation 之后 React
// 的处理器（含各控件自己的 onClick/onSubmit）根本不会执行，比事后补丁更彻底。
// 键鼠都覆盖：Enter/Space 激活按钮同样派发原生 click；输入框回车走 submit。
import { useEffect, useState } from 'react'
import { Outlet } from 'react-router-dom'
import { GuestPromptDialog } from './GuestPromptDialog'

// 左 rail 标了 data-guest-exempt，导航对游客照常可用——「能进页但页内全禁用」。
const INTERACTIVE = [
  'a[href]', 'button', 'input', 'select', 'textarea', 'label', 'summary',
  '[role="button"]', '[role="tab"]', '[contenteditable="true"]',
].join(',')
const EXEMPT = '[data-guest-exempt]'

function isExempt(target: EventTarget | null): boolean {
  return target instanceof Element && target.closest(EXEMPT) !== null
}

export function GuestShell() {
  const [promptOpen, setPromptOpen] = useState(false)

  useEffect(() => {
    const block = (event: Event) => {
      const target = event.target
      if (!(target instanceof Element) || isExempt(target)) return
      const submitEvent = event.type === 'submit'
      // submit 的目标是 <form> 本身，不在 INTERACTIVE 里，命中判断要看触发的控件。
      if (!submitEvent && target.closest(INTERACTIVE) === null) return
      event.preventDefault()
      event.stopPropagation()
      setPromptOpen(true)
    }
    document.addEventListener('click', block, true)
    document.addEventListener('submit', block, true)
    return () => {
      document.removeEventListener('click', block, true)
      document.removeEventListener('submit', block, true)
    }
  }, [])

  return (
    <>
      <Outlet />
      <GuestPromptDialog open={promptOpen} onClose={() => setPromptOpen(false)} />
    </>
  )
}
