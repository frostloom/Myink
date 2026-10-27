import type { PropType } from 'vue';
import { defineComponent, onMounted, onUnmounted, h as renderNode, shallowRef, type VNodeChild } from 'vue';
import { resizeTextarea } from "../../../../src/lib/resizeTextarea";
import styles from "../../../../src/pages/admin/AdminResources.module.css";
export const AdminDialog = defineComponent((props: {
    title: string;
    contained?: boolean;
    children?: VNodeChild;
    onClose: () => void;
    busy: boolean;
}, { slots }) => {
    const ref = shallowRef<HTMLDialogElement | null>(null);
    onMounted(() => {
        const cleanup = (() => {
            ref.value?.querySelectorAll("textarea").forEach(resizeTextarea);
        })();
        if (typeof cleanup === "function")
            onUnmounted(cleanup);
    });
    onMounted(() => {
        const cleanup = (() => {
            const previous = document.activeElement as HTMLElement | null;
            const dialog = ref.value;
            if (typeof dialog?.showModal === "function")
                dialog.showModal();
            else
                dialog?.setAttribute("open", "");
            const backgrounds: HTMLElement[] = [document.documentElement, document.body];
            for (let parent = dialog?.parentElement; parent; parent = parent.parentElement) {
                if (!backgrounds.includes(parent) && /auto|scroll/.test(getComputedStyle(parent).overflowY))
                    backgrounds.push(parent);
            }
            const previousOverflow = backgrounds.map((element: HTMLElement) => element.style.overflowY);
            backgrounds.forEach((element: HTMLElement) => { element.style.overflowY = "hidden"; });
            const resize = () => dialog?.querySelectorAll("textarea").forEach(resizeTextarea);
            resize();
            dialog?.addEventListener("input", resize);
            window.addEventListener("resize", resize);
            const observer = new MutationObserver(resize);
            if (dialog)
                observer.observe(dialog, { childList: true, subtree: true, characterData: true });
            return () => {
                observer.disconnect();
                dialog?.removeEventListener("input", resize);
                window.removeEventListener("resize", resize);
                backgrounds.forEach((element: HTMLElement, index: number) => { element.style.overflowY = previousOverflow[index]; });
                if (previous?.isConnected)
                    previous.focus();
            };
        })();
        if (typeof cleanup === "function")
            onUnmounted(cleanup);
    });
    return () => {
        return (renderNode("dialog", { ref: ref, "class": [styles.dialog, props.contained && styles.containedDialog], "aria-label": props.title, "onCancel": (e: Event) => {
                e.preventDefault();
                if (!props.busy)
                    props.onClose();
            } }, [
            renderNode("header", { "class": styles.dialogHead }, [
                renderNode("h2", {}, [props.title]), renderNode("button", { "type": "button", "class": "btn btn-quiet", "aria-label": "关闭", "disabled": props.busy, "onClick": props.onClose }, ["×"])
            ]), slots.default?.() ?? props.children
        ]));
    };
}, {
    inheritAttrs: false,
    props: {
        contained: { type: Boolean, default: false },
        title: { type: String as PropType<string>, required: true },
        children: { default: undefined, type: null, required: false },
        onClose: { type: Function as PropType<() => void>, required: true },
        busy: { type: Boolean as PropType<boolean>, required: true }
    }
});
