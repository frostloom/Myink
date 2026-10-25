import { Link } from 'react-router-dom'
import type { AdminAccessLog } from '../../lib/adminApi'
import { Disclosure } from './ExecutionContent'

const actions: Record<string, string> = {
  overview: '查看平台概览', trends: '查看数据趋势', users: '查看用户列表', user: '查看账号详情',
  projects: '查看作品列表', project: '查看作品详情', chapters: '查看章节列表', chapter: '查看章节正文',
  context: '查看作品设定', tasks: '查看任务列表', task: '查看任务详情', task_runs: '查看任务执行记录',
  task_chapters: '查看任务生成的章节', generation_tasks: '查看作品创作记录', snapshot: '查看章节创作依据',
  findings: '查看创作问题', runs: '查看模型调用列表', run: '查看模型调用详情', access_logs: '查看管理操作记录',
  invitations: '查看邀请码列表', create_invitation: '创建邀请码', revoke_invitation: '撤销邀请码',
  feedback: '查看问题反馈', feedback_status: '更新反馈处理状态',
}
export function AccessLogContent({ entry }: { entry: AdminAccessLog }) {
  const action = entry.action.startsWith('admin.') ? entry.action.slice(6) : ''
  const targets = entry.target.split(',').map(part => part.split('='))
  const names: Record<string, string> = { user_id: '用户', project_id: '作品', task_id: '任务', chapter_id: '章节', run_id: '模型调用', snapshot_id: '章节创作依据', invitation_id: '邀请码', feedback_id: '问题反馈' }
  const target = entry.target === 'collection' ? '列表或平台汇总' : targets.map(([key]) => names[key] ?? '相关记录').join('、')
  return <>
    <td><Link to={`/admin/users/${entry.actor_id}`}>查看管理员账号</Link></td>
    <td>{actions[action] ?? '其他管理操作'}</td>
    <td>{target}<Disclosure title="查看定位信息"><p>操作标识：{entry.action}</p><p>目标记录：{entry.target}</p><p>管理员账号编号：{entry.actor_id}</p></Disclosure></td>
  </>
}
