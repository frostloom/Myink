import { defineComponent, Fragment, h as renderNode, shallowRef, type PropType } from 'vue';
import { RouterLink as Link, useRoute } from 'vue-router';
import type { AdminAccessLog } from "../../../../src/lib/adminApi";
import { AdminDialog } from "./AdminDialog";
const actions: Record<string, string> = {
    overview: '查看平台概览', trends: '查看数据趋势', users: '查看用户列表', user: '查看账号详情',
    projects: '查看作品列表', project: '查看作品详情', chapters: '查看章节列表', chapter: '查看章节正文',
    context: '查看作品设定', tasks: '查看任务列表', task: '查看任务详情', task_runs: '查看任务执行记录',
    task_chapters: '查看任务生成的章节', generation_tasks: '查看作品创作记录', snapshot: '查看章节创作依据',
    findings: '查看创作问题', runs: '查看模型调用列表', run: '查看模型调用详情', access_logs: '查看管理操作记录',
    invitations: '查看邀请码列表', create_invitation: '创建邀请码', revoke_invitation: '撤销邀请码',
    feedback: '查看问题反馈', feedback_status: '更新反馈处理状态',
};
export const AccessLogContent = defineComponent((props: { entry: AdminAccessLog }) => {
    const route = useRoute();
    const open = shallowRef(false);
    return () => {
    const { entry } = props;
    const action = entry.action.startsWith('admin.') ? entry.action.slice(6) : '';
    const targets = entry.target.split(',').map((part: string) => part.split('='));
    const names: Record<string, string> = { user_id: '用户', project_id: '作品', task_id: '任务', chapter_id: '章节', run_id: '模型调用', snapshot_id: '章节创作依据', invitation_id: '邀请码', feedback_id: '问题反馈' };
    const target = entry.target === 'collection' ? '列表或平台汇总' : targets.map(([key]) => names[key] ?? '相关记录').join('、');
    return renderNode(Fragment, {}, [
        renderNode("td", {}, [renderNode(Link, { "to": { path: `/admin/users/${entry.actor_id}`, query: { returnTo: route.fullPath } } }, { default: () => ["查看管理员账号"] })]), renderNode("td", {}, [actions[action] ?? "其他管理操作"]), renderNode("td", {}, [
            target, renderNode("button", { type: 'button', class: 'btn btn-quiet', onClick: (event: MouseEvent) => { (event.currentTarget as HTMLButtonElement).focus({ preventScroll: true }); open.value = true; } }, ['查看定位信息']),
            open.value && renderNode(AdminDialog, { title: '访问日志详情', busy: false, onClose: () => { open.value = false; }, children: [renderNode("p", {}, [
                        "操作标识：", entry.action
                    ]), renderNode("p", {}, [
                        "目标记录：", entry.target
                    ]), renderNode("p", {}, [
                        "管理员账号编号：", entry.actor_id
                    ])] })
        ])
    ]);
    };
}, { inheritAttrs: false, props: { entry: { type: Object as PropType<AdminAccessLog>, required: true } } });
