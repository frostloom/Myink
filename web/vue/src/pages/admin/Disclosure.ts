import type { PropType } from 'vue';
import { defineComponent, h as renderNode, shallowRef, type VNodeChild } from 'vue';
import styles from "../../../../src/pages/admin/ExecutionDetail.module.css";
export const Disclosure = defineComponent((props: {
    title: VNodeChild;
    children: VNodeChild;
    defaultOpen?: boolean;
}) => {
    const open = shallowRef((props.defaultOpen ?? false));
    const setOpen = (next: typeof open.value | ((old: typeof open.value) => typeof open.value)) => { open.value = typeof next === "function" ? next(open.value) : next; };
    return () => {
        return renderNode("details", { "open": open.value, "class": styles.disclosure, "onToggle": (event: Event) => setOpen((event.currentTarget as HTMLInputElement & HTMLSelectElement & HTMLDetailsElement).open) }, [
            renderNode("summary", {}, [props.title]), open.value && props.children
        ]);
    };
}, {
    inheritAttrs: false,
    props: {
        title: { type: null, required: true },
        children: { type: null, required: true },
        defaultOpen: { type: Boolean as PropType<boolean>, default: undefined }
    }
});
