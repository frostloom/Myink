import { afterEach,expect,it,vi } from 'vitest'
import { cleanup,render } from '@testing-library/vue'
import { flushPromises } from '@vue/test-utils'
import { ref } from 'vue'
import { createMemoryHistory,createRouter } from 'vue-router'
import { adminApi } from '../../../../src/lib/adminApi'
import { ApiError } from '../../../../src/lib/api'
import { adminContextKey } from './context'
import { ProjectDetailPage } from './ProjectDetail'
import { TaskDetailPage } from './TaskDetail'
import { RunDetailPage } from './RunDetail'
import { UserDetailPage } from './UserDetail'
afterEach(()=>{cleanup();vi.restoreAllMocks()})
it.each(['project','task','run','user'] as const)('uses the current token in a retained %s detail view',async kind=>{
 const denied=new ApiError(404,'not_found',{})
 const project=vi.spyOn(adminApi,'getProject').mockRejectedValue(denied)
 const task=vi.spyOn(adminApi,'getTask').mockRejectedValue(denied)
 const run=vi.spyOn(adminApi,'getRun').mockRejectedValue(denied)
 const user=vi.spyOn(adminApi,'getUser').mockRejectedValue(denied)
 vi.spyOn(adminApi,'listTaskRuns').mockResolvedValue({items:[],total:0,offset:0,limit:25})
 vi.spyOn(adminApi,'listRuns').mockResolvedValue({items:[],total:0,offset:0,limit:25})
 const component={project:ProjectDetailPage,task:TaskDetailPage,run:RunDetailPage,user:UserDetailPage}[kind]
 const request={project,task,run,user}[kind]
 const parameter={project:'projectId',task:'taskId',run:'runId',user:'userId'}[kind]
 const token=ref('before-renewal')
 const router=createRouter({history:createMemoryHistory(),routes:[{path:'/detail/:'+parameter,component}]})
 await router.push('/detail/1');await router.isReady()
 render(component,{global:{plugins:[router],provide:{[adminContextKey as symbol]:{get token(){return token.value},onForbidden:vi.fn()}}}})
 await flushPromises();expect(request.mock.calls[0][0]).toBe('before-renewal')
 token.value='after-renewal';await flushPromises()
 expect(request.mock.calls.at(-1)?.[0]).toBe('after-renewal')
})
