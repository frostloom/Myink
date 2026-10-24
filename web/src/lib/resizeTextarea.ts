export function resizeTextarea(element: HTMLTextAreaElement) {
  element.style.height = 'auto'
  const border = element.offsetHeight - element.clientHeight
  element.style.height = `${element.scrollHeight + border}px`
  element.style.overflowY = 'hidden'
}
