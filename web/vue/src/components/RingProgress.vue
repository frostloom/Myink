<script lang="ts">
import type { PropType } from 'vue'
import { defineComponent, h, computed } from 'vue'

/** 环形进度：给「一次跑几分钟、中途只有字数在长」的长调用用（短篇成稿/改稿）。

 * 单值驱动（0–1）。环里是百分比 + 阶段名——光有百分比，用户仍会问「它到底在干嘛」。
 * `indeterminate` 用在没有实时数字的阶段（审稿、补写）：环不再表示刻度，只用转动的短弧
 * 说明「还活着」，比停在一个假百分比上更诚实。
 */
import styles from "../../../src/components/RingProgress.module.css";
const STROKE = 10;
interface Props {
    /** 0–1，超出范围会被夹住。 */
    value: number;
    /** 读屏用的名字；屏幕上看不见它。 */
    ariaLabel: string;
    /** 环内的阶段名，跟在百分比下面。 */
    label: string;
    /** 没有实时刻度：只转圈不给百分比。 */
    indeterminate?: boolean;
    size?: number;
}
export const RingProgress = defineComponent({
    name: "RingProgress",
    props: { value: { type: Number as PropType<(Props)["value"]>, required: true }, ariaLabel: { type: String as PropType<(Props)["ariaLabel"]>, required: true }, label: { type: String as PropType<(Props)["label"]>, required: true }, indeterminate: { type: Boolean as PropType<(Props)["indeterminate"]>, required: false, default: undefined }, size: { type: Number as PropType<(Props)["size"]>, required: false, default: undefined } },
    setup(props: Props) {
        const value = computed(() => props.value);
        const ariaLabel = computed(() => props.ariaLabel);
        const label = computed(() => props.label);
        const indeterminate = computed(() => props.indeterminate ?? false);
        const size = computed(() => props.size ?? 148);
        const clamped = computed(() => Math.min(Math.max(value.value, 0), 1));
        const radius = computed(() => (size.value - STROKE) / 2);
        const circumference = computed(() => 2 * Math.PI * radius.value);
        const percent = computed(() => Math.round(clamped.value * 100));
        return () => {
            return (h("div", { "class": styles.ring, "style": { width: `${size.value}px`, height: `${size.value}px` }, "role": "progressbar", "aria-label": ariaLabel.value, "aria-valuemin": indeterminate.value ? undefined : 0, "aria-valuemax": indeterminate.value ? undefined : 100, "aria-valuenow": indeterminate.value ? undefined : percent.value }, [h("svg", { "class": styles.svg, "viewBox": `0 0 ${size.value} ${size.value}`, "aria-hidden": "true" }, [h("circle", { "class": styles.track, "cx": size.value / 2, "cy": size.value / 2, "r": radius.value, "strokeWidth": STROKE, "fill": "none" }, []), h("circle", { "class": [styles.fill, indeterminate.value ? styles.pulse : ''].join(' '), "cx": size.value / 2, "cy": size.value / 2, "r": radius.value, "strokeWidth": STROKE, "fill": "none", "strokeLinecap": "round", "strokeDasharray": circumference.value, "strokeDashoffset": indeterminate.value ? circumference.value * 0.75
                            : circumference.value * (1 - clamped.value) }, [])]), h("div", { "class": styles.center, "aria-hidden": "true" }, [h("strong", {}, [indeterminate.value ? '···' : `${percent.value}%`]), h("span", {}, [label.value])])]));
        };
    }
});

export default RingProgress

</script>
