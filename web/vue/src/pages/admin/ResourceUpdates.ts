import { useMemoryFormGuard } from '../../composables/useMemoryFormGuard';
import type { PropType } from 'vue';
import { Fragment, defineComponent, onMounted, onUnmounted, h as renderNode, shallowRef, watch } from 'vue';
import { writingResources as api, resourceError, type ResourceSnapshot, type ResourceUpdate, } from "../../../../src/lib/writingResources";
import { AdminDialog } from "./AdminDialog";
export interface ResourceUpdateGate {
    beforeGenerate: () => Promise<boolean>;
}
export const ResourceUpdates = defineComponent((props: {
    projectId: string;
    autoOpen?: boolean;
    onAdopt?: (s: ResourceSnapshot) => void;
}, { expose }) => {
    const updates = shallowRef<ResourceUpdate[]>([]);
    const setUpdates = (next: typeof updates.value | ((old: typeof updates.value) => typeof updates.value)) => { updates.value = typeof next === "function" ? next(updates.value) : next; };
    const revision = shallowRef(0);
    const setRevision = (next: typeof revision.value | ((old: typeof revision.value) => typeof revision.value)) => { revision.value = typeof next === "function" ? next(revision.value) : next; };
    const selected = shallowRef<string[]>([]);
    const setSelected = (next: typeof selected.value | ((old: typeof selected.value) => typeof selected.value)) => { selected.value = typeof next === "function" ? next(selected.value) : next; };
    const open = shallowRef(false);
    const setOpen = (next: typeof open.value | ((old: typeof open.value) => typeof open.value)) => { open.value = typeof next === "function" ? next(open.value) : next; };
    const busy = shallowRef(false);
    const setBusy = (next: typeof busy.value | ((old: typeof busy.value) => typeof busy.value)) => { busy.value = typeof next === "function" ? next(busy.value) : next; };
    const error = shallowRef("");
    const setError = (next: typeof error.value | ((old: typeof error.value) => typeof error.value)) => { error.value = typeof next === "function" ? next(error.value) : next; };
    const pending = shallowRef<((proceed: boolean) => void) | null | null>(null);
    const requestSerial = shallowRef(0);
    const active = shallowRef(true);
    const waiting = shallowRef(false);
    useMemoryFormGuard(() => open.value && selected.value.length > 0);
    const setWaiting = (next: typeof waiting.value | ((old: typeof waiting.value) => typeof waiting.value)) => { waiting.value = typeof next === "function" ? next(waiting.value) : next; };
    function finish(proceed: boolean) {
        const resolve = pending.value;
        pending.value = null;
        setWaiting(false);
        resolve?.(proceed);
    }
    const gate: ResourceUpdateGate = {
        async beforeGenerate() {
            if (pending.value)
                return false;
            ++requestSerial.value;
            setBusy(true);
            setError("");
            try {
                const [u, snapshot] = await Promise.all([
                    api.updates(props.projectId),
                    api.snapshot(props.projectId),
                ]);
                if (!active.value)
                    return false;
                const eligible = u.items.filter((update: ResourceUpdate) => !snapshot.selections.some((selection: import("../../../../src/lib/writingResources").ResourceSelection) => selection.resource_id === update.resource_id && selection.personal_override));
                setUpdates(eligible);
                setRevision(snapshot.revision);
                setSelected(eligible.map((update: ResourceUpdate) => update.resource_id));
                if (!eligible.some((update: ResourceUpdate) => !update.dismissed))
                    return true;
            }
            catch (error) {
                setError(resourceError(error));
            }
            finally {
                setBusy(false);
            }
            if (!active.value)
                return false;
            setOpen(true);
            setWaiting(true);
            return new Promise<boolean>((resolve: (value: boolean | PromiseLike<boolean>) => void) => {
                pending.value = resolve;
            });
        },
    };
    expose(gate);
    onMounted(() => {
        const cleanup = (() => {
            active.value = true;
            return () => {
                active.value = false;
                pending.value?.(false);
                pending.value = null;
            };
        })();
        if (typeof cleanup === "function")
            onUnmounted(cleanup);
    });
    watch([() => props.projectId, () => (props.autoOpen ?? true)], (_next, _old, onCleanup) => {
        const cleanup = (() => {
            let live = true;
            const request = ++requestSerial.value;
            Promise.all([api.updates(props.projectId), api.snapshot(props.projectId)]).then(([u, s]) => {
                if (!live || request !== requestSerial.value)
                    return;
                const eligible = u.items.filter((i: ResourceUpdate) => !s.selections.some((v: import("../../../../src/lib/writingResources").ResourceSelection) => v.resource_id === i.resource_id && v.personal_override));
                setUpdates(eligible);
                setRevision(s.revision);
                setSelected(eligible.map((i: ResourceUpdate) => i.resource_id));
                setOpen((props.autoOpen ?? true) && eligible.some((i: ResourceUpdate) => !i.dismissed));
            }).catch(e => {
                if (live)
                    setError(resourceError(e));
            });
            return () => {
                live = false;
            };
        })();
        if (typeof cleanup === "function")
            onCleanup(cleanup);
    }, { immediate: true, flush: "post" });
    async function close() {
        setBusy(true);
        try {
            await api.dismiss(props.projectId, updates.value.filter((i: ResourceUpdate) => !i.dismissed).map((i: ResourceUpdate) => ({
                resource_id: i.resource_id,
                target_generation: i.target_generation,
            })));
            setUpdates((old: ResourceUpdate[]) => old.map((i: ResourceUpdate) => ({ ...i, dismissed: true })));
            setOpen(false);
            setError("");
            finish(true);
        }
        catch (e) {
            setError(resourceError(e));
        }
        finally {
            setBusy(false);
        }
    }
    async function adopt() {
        setBusy(true);
        try {
            const s = await api.adopt(props.projectId, revision.value, updates.value.filter((i: ResourceUpdate) => selected.value.includes(i.resource_id)).map((i: ResourceUpdate) => ({
                resource_id: i.resource_id,
                target_generation: i.target_generation,
            })));
            props.onAdopt?.(s);
            setRevision(s.revision);
            setUpdates((old: ResourceUpdate[]) => old.filter((i: ResourceUpdate) => !selected.value.includes(i.resource_id)));
            setOpen(false);
            setError("");
            finish(true);
        }
        catch (e) {
            setError(resourceError(e));
        }
        finally {
            setBusy(false);
        }
    }
    async function review() {
        setBusy(true);
        try {
            const [u, s] = await Promise.all([
                api.updates(props.projectId),
                api.snapshot(props.projectId),
            ]);
            const eligible = u.items.filter((i: ResourceUpdate) => !s.selections.some((v: import("../../../../src/lib/writingResources").ResourceSelection) => v.resource_id === i.resource_id && v.personal_override));
            setUpdates(eligible);
            setRevision(s.revision);
            setSelected(eligible.map((i: ResourceUpdate) => i.resource_id));
            setOpen(true);
            setError("");
        }
        catch (e) {
            setError(resourceError(e));
        }
        finally {
            setBusy(false);
        }
    }
    return () => {
        return (renderNode(Fragment, {}, [
            renderNode("button", { "class": "btn btn-quiet", "disabled": busy.value, "onClick": () => void review() }, [
                "查看资源更新", updates.value.length ? `（${updates.value.length}）` : ""
            ]), error.value && !open.value && renderNode("p", {}, [error.value]), open.value && (renderNode(AdminDialog, { "title": "写作资源更新", "busy": busy.value, "onClose": () => void close(), children: [renderNode("p", {}, ["只更新勾选项；本书个人覆盖保持不变，当前运行任务继续使用原快照。"]), updates.value.length === 0 && renderNode("p", {}, ["暂无可采用更新。"]), updates.value.map((i: ResourceUpdate) => (renderNode("label", { "key": i.resource_id, "style": { display: "block", margin: "1rem 0" } }, [
                        renderNode("input", { "type": "checkbox", "checked": selected.value.includes(i.resource_id), "onChange": (e: Event) => setSelected((old: string[]) => (e.target as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).checked ? [...old, i.resource_id] : old.filter((id: string) => id !== i.resource_id)) }, []), i.name, " · v", i.current_version, " → v", i.target_version, " ·", " ", i.action === "rollback" ? "管理员回退" : "新发布", " · 发布标识", " ", i.target_generation, renderNode("br", {}, []), i.note, i.dismissed ? " · 已忽略（仍可采用）" : ""
                    ]))), error.value && renderNode("p", { "role": "alert" }, [error.value]), waiting.value && error.value && (renderNode("button", { "class": "btn", "disabled": busy.value, "onClick": () => {
                            setOpen(false);
                            finish(true);
                        } }, ["检查失败，仍使用当前快照"])), waiting.value && (renderNode("button", { "class": "btn", "disabled": busy.value, "onClick": () => {
                            setOpen(false);
                            finish(false);
                        } }, ["取消本次生成"])), renderNode("button", { "class": "btn", "disabled": busy.value, "onClick": () => void close() }, [waiting.value ? "继续使用当前快照" : "暂不更新"]), renderNode("button", { "class": "btn btn-primary", "disabled": busy.value || !selected.value.length, "onClick": () => void adopt() }, ["采用勾选更新"]), renderNode("button", { "class": "btn", "disabled": busy.value, "onClick": () => void review() }, ["重新检查版本"])] }))
        ]));
    };
}, {
    inheritAttrs: false,
    props: {
        projectId: { type: String as PropType<string>, required: true },
        autoOpen: { type: Boolean as PropType<boolean>, default: undefined },
        onAdopt: { type: Function as PropType<(s: ResourceSnapshot) => void>, default: undefined }
    }
});
