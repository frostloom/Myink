import { defineComponent, h, type VNode, type PropType } from 'vue'
import { createRouter, createMemoryHistory, RouterView, type HistoryState, type Router } from 'vue-router'
export function createMemoryRouter(routes: {path:string;element:VNode}[], options: {initialEntries:(string|{pathname:string;state?:Record<string,unknown>})[]}) {
  const history=createMemoryHistory()
  const entry=options.initialEntries[0]
  history.replace(typeof entry==='string'?entry:entry.pathname,typeof entry==='string'?undefined:entry.state as HistoryState)
  const router=createRouter({history,routes:routes.map(r=>({path:r.path,component:{setup:()=>()=>h(r.element)}}))})
  let initial = true
  router.afterEach(() => { if (initial) { initial=false; if(typeof entry!=='string' && entry.state) history.replace(history.location,{...history.state,...entry.state} as HistoryState) } })
  const navigate=(path:string,opts?:{replace?:boolean;state?:Record<string,unknown>}) => { const target=router.resolve(path);const location={path:target.path,query:target.query,hash:target.hash,state:opts?.state as HistoryState,force:opts?.replace===true};return opts?.replace?router.replace(location):router.push(location) }

  return Object.assign(router,{navigate,state:{location:{get state(){return history.state}}}})
}
export const RouterProvider=defineComponent({props:{router:{type:Object as PropType<Router>,required:true}},setup:()=>()=>h(RouterView)})
