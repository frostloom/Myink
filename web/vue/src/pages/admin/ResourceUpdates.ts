import { useMemoryFormGuard } from '../../composables/useMemoryFormGuard';
import { defineComponent, onUnmounted, h, ref, watch, type PropType } from 'vue';
import { writingResources as api, resourceError, type ResourceSnapshot, type ResourceUpdate } from '../../../../src/lib/writingResources';
import { getSession } from '../../../../src/lib/token';
import { AdminDialog } from './AdminDialog';
export interface ResourceUpdateGate { beforeGenerate: () => Promise<boolean> }

// A failed dismissal request must not repeatedly interrupt the same browser session.
function dismissalKey(projectId: string, update: ResourceUpdate) {
    return `myink:resource-update:${getSession()?.userId ?? 'anonymous'}:${projectId}:${update.resource_id}:${update.target_generation}`;
}
export const ResourceUpdates = defineComponent((props: {
    projectId: string; autoOpen?: boolean; paused?: boolean; onAdopt?: (s: ResourceSnapshot) => void;
}, { expose }) => {
    const updates = ref<ResourceUpdate[]>([]), selected = ref<string[]>([]);
    const revision = ref(0), open = ref(false), busy = ref(false), error = ref('');
    const waiting = ref(false), overridden = ref<string[]>([]);
    const dismissed = new Set<string>();
    const origins = ref<Record<string, 'platform'|'personal'>>({});
    let checking: Promise<boolean> | null = null, checkingProject = '', gateChecking = false;
    let serial = 0, active = true, pending: ((proceed: boolean) => void) | null = null;
    useMemoryFormGuard(() => open.value && selected.value.length > 0);
    function finish(proceed: boolean) { const resolve = pending; pending = null; waiting.value = false; resolve?.(proceed); }
    function wasDismissed(projectId: string, update: ResourceUpdate) {
        const key = dismissalKey(projectId, update);
        if (dismissed.has(key)) return true;
        try { return sessionStorage.getItem(key) === '1'; } catch { return false; }
    }
    function remember(projectId: string, items: ResourceUpdate[]) {
        for (const update of items) {
            const key = dismissalKey(projectId, update); dismissed.add(key);
            try { sessionStorage.setItem(key, '1'); } catch { /* Memory still suppresses repeated checks. */ }
        }
    }
    function check(): Promise<boolean> {
        if (checking && checkingProject === props.projectId) return checking;
        checkingProject = props.projectId;
        const request = performCheck();
        checking = request;
        void request.finally(() => { if (checking === request) checking = null; });
        return request;
    }
    async function performCheck(): Promise<boolean> {
        const request = ++serial, pid = props.projectId;
        busy.value = true; error.value = '';
        try {
            const [available, snapshot] = await Promise.all([api.updates(pid), api.snapshot(pid)]);
            if (!active || request !== serial) return false;
            updates.value = available.items.filter(update => {
                const matches = snapshot.selections.filter(item => item.resource_id === update.resource_id);
                const current = matches.length === 1 ? matches[0] : undefined;
                return current && current.generation !== update.target_generation
                    && !update.dismissed && !wasDismissed(pid, update);
            });
            origins.value = Object.fromEntries(snapshot.selections.map(item => [item.resource_id,item.origin]));
            revision.value = snapshot.revision;
            overridden.value = snapshot.selections.filter(item => item.personal_override).map(item => item.resource_id);
            selected.value = updates.value.filter(item => !overridden.value.includes(item.resource_id)).map(item => item.resource_id);
            open.value = updates.value.length > 0;
            return true;
        } catch (cause) {
            if (active && request === serial) { error.value = resourceError(cause); updates.value = []; selected.value = []; open.value = false; }
            return active && request === serial;
        } finally { if (active && request === serial) busy.value = false; }
    }
    const gate: ResourceUpdateGate = {
        async beforeGenerate() {
            if (pending || gateChecking || (busy.value && !checking)) return false;
            gateChecking = true;
            const pid = props.projectId;
            try {
                if (!await check() || !active || pid !== props.projectId) return false;
                open.value = updates.value.length > 0;
                if (!open.value) return true;
                waiting.value = true;
                return await new Promise<boolean>(resolve => { pending = resolve; });
            } finally { gateChecking = false; }
        },
    };
    expose(gate);
    watch(() => props.projectId, () => { finish(false); open.value = false; void check().then(current => { if (current && props.autoOpen === false) open.value = false; }); }, { immediate: true });
    watch(() => props.autoOpen, value => { if (value !== false) void check(); });
    onUnmounted(() => { active = false; serial++; finish(false); });
    async function close(proceed = true) {
        const pid = props.projectId, items = [...updates.value];
        remember(pid, items); open.value = false; error.value = ''; finish(proceed);
        if (items.length) {
            try { await api.dismiss(pid, items.map(item => ({ resource_id: item.resource_id, target_generation: item.target_generation }))); }
            catch { /* The browser remembers the decision even while offline. */ }
        }
    }
    async function adopt() {
        if (busy.value) return;
        const request = ++serial, pid = props.projectId;
        const chosen = updates.value.filter(item => selected.value.includes(item.resource_id));
        busy.value = true;
        try {
            const saved = await api.adopt(pid, revision.value, chosen.map(item => ({ resource_id: item.resource_id, target_generation: item.target_generation })));
            if (!active || request !== serial) return;
            // Unchecked updates were explicitly declined in this review.
            const declined = updates.value.filter(item => !selected.value.includes(item.resource_id));
            remember(pid, declined);
            if (declined.length) void api.dismiss(pid, declined.map(item => ({resource_id:item.resource_id,target_generation:item.target_generation}))).catch(() => {});
            props.onAdopt?.(saved); revision.value = saved.revision; open.value = false; error.value = ''; finish(true);
        } catch (cause) { if (active && request === serial) error.value = resourceError(cause); }
        finally { if (active && request === serial) busy.value = false; }
    }
    return () => [
        error.value && !open.value && h('p', { role: 'status' }, '暂时无法检查资源更新，继续保留当前资源。'),
        open.value && !props.paused && h(AdminDialog, {title:'写作资源更新', busy:busy.value, onClose:()=>void close(), children:[
            h('p', {}, '所选资源有新版本。仅在确认后采用勾选项；未勾选的本书个人修改会保留；历史章节和运行中的任务保持不变。'),
            ...updates.value.map(item => h('label', {key:item.resource_id, style:{display:'block',margin:'1rem 0'}}, [
                h('input', {type:'checkbox',checked:selected.value.includes(item.resource_id),disabled:busy.value,onChange:(event:Event)=>{
                    selected.value = (event.target as HTMLInputElement).checked ? [...selected.value,item.resource_id] : selected.value.filter(id=>id!==item.resource_id);
                }}), `${item.name} · v${item.current_version} → v${item.target_version} · ${origins.value[item.resource_id]==='personal'?'个人资源更新':item.action==='rollback'?'管理员回退':'管理员发布'}`,h('br'),item.note, overridden.value.includes(item.resource_id) && h('strong', {style:{display:'block'}}, '本书已作个人修改；采用将覆盖本书个人修改，默认保留当前版本。'),
            ])),
            error.value && h('p',{role:'alert'},error.value),
            waiting.value && h('button',{class:'btn',disabled:busy.value,onClick:()=>void close(false)},'取消本次生成'),
            h('button',{class:'btn',disabled:busy.value,onClick:()=>void close()},waiting.value?'继续使用当前快照':'暂不更新'),
            h('button',{class:'btn btn-primary',disabled:busy.value||!selected.value.length,onClick:()=>void adopt()},'采用勾选更新'),
            h('button',{class:'btn',disabled:busy.value,onClick:()=>void check().then(()=>{if(!open.value)finish(true);})},'重新检查版本'),
        ]}),
    ];
}, {inheritAttrs:false,props:{
    projectId:{type:String as PropType<string>,required:true},
    paused:{type:Boolean,default:false},
    autoOpen:{type:Boolean as PropType<boolean>,default:undefined},
    onAdopt:{type:Function as PropType<(s:ResourceSnapshot)=>void>,default:undefined},
}});
