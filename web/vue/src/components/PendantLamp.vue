<script lang="ts">
import { defineComponent, h, useId } from 'vue';

import type { PropType } from 'vue'
import { LAMP_HANG, type LampId } from "../../../src/lib/theme";
type LampProps = {
    id: LampId;
    lit: boolean;
    className?: string;
    /** 挂在页面上时绳子另画，这里只留灯头，绳长才能跟着拖拽变。 */
    hanging?: boolean;
};
function gid(prefix: string, name: string): string {
    return `${prefix}-${name}`;
}
function Shade({ prefix, lit }: {
    prefix: string;
    lit: boolean;
}) {
    const fabric = gid(prefix, 'fabric');
    const wood = gid(prefix, 'wood');
    const clip = gid(prefix, 'clip');
    return (h("g", {}, [h("defs", {}, [h("linearGradient", { "id": fabric, "x1": "0", "y1": "0", "x2": "1", "y2": "0" }, [h("stop", { "offset": "0%", "stop-color": "#d8ccb6" }, []), h("stop", { "offset": "14%", "stop-color": "#f6efe4" }, []), h("stop", { "offset": "46%", "stop-color": "#fbf7f0" }, []), h("stop", { "offset": "78%", "stop-color": "#efe3d2" }, []), h("stop", { "offset": "100%", "stop-color": "#c9bba6" }, [])]), h("radialGradient", { "id": wood, "cx": "32%", "cy": "28%", "r": "75%" }, [h("stop", { "offset": "0%", "stop-color": "#c48962" }, []), h("stop", { "offset": "48%", "stop-color": "#7a4630" }, []), h("stop", { "offset": "100%", "stop-color": "#3d2418" }, [])]), h("clipPath", { "id": clip }, [h("path", { "d": "M62 186 C62 174 138 174 138 186 L142 252 C142 266 58 266 58 252 Z" }, [])])]), h("path", { "d": "M100 2 C104 36 96 70 100 104 C104 132 96 150 100 168", "fill": "none", "stroke": "#cbbda6", "stroke-width": "1.7" }, []), h("path", { "d": "M100 2 C96 36 104 70 100 104 C96 132 104 150 100 168", "fill": "none", "stroke": "#8f806c", "stroke-width": "0.7", "opacity": "0.75" }, []), h("ellipse", { "cx": "128", "cy": "276", "rx": "36", "ry": "7", "fill": "#000", "opacity": "0.07" }, []), h("ellipse", { "cx": "100", "cy": "176", "rx": "8.5", "ry": "7.6", "fill": `url(#${wood})` }, []), h("ellipse", { "cx": "97", "cy": "173", "rx": "2.6", "ry": "1.6", "fill": "#fff", "opacity": "0.28" }, []), h("rect", { "x": "96.2", "y": "182", "width": "7.6", "height": "3.4", "rx": "1", "fill": "#b7aea2" }, []), h("g", { "clip-path": `url(#${clip})` }, [h("path", { "d": "M62 186 C62 174 138 174 138 186 L142 252 C142 266 58 266 58 252 Z", "fill": `url(#${fabric})` }, []), Array.from({ length: 16 }, (_, index) => (h("line", { "key": index, "x1": 66 + index * 4.6, "y1": "174", "x2": 64 + index * 4.6, "y2": "268", "stroke": "#e3d5c2", "stroke-width": "0.7", "opacity": "0.7" }, []))), h("rect", { "x": "76", "y": "174", "width": "3.3", "height": "94", "fill": "#d24b42" }, []), h("rect", { "x": "116", "y": "174", "width": "3.3", "height": "94", "fill": "#d24b42" }, [])]), h("ellipse", { "cx": "100", "cy": "186", "rx": "38", "ry": "9", "fill": "#f8f3ea" }, []), h("ellipse", { "cx": "100", "cy": "186", "rx": "31", "ry": "5.2", "fill": "#efe4d4" }, []), h("ellipse", { "cx": "100", "cy": "256", "rx": "40", "ry": "9", "fill": lit ? '#fff3d8' : '#e4d8c6' }, []), h("ellipse", { "cx": "100", "cy": "256", "rx": "27", "ry": "4.6", "fill": lit ? '#fffdf8' : '#efe6d6', "opacity": lit ? 1 : 0.45 }, [])]));
}
function Cube({ prefix, lit }: {
    prefix: string;
    lit: boolean;
}) {
    const chrome = gid(prefix, 'chrome');
    const paper = gid(prefix, 'paper');
    return (h("g", {}, [h("defs", {}, [h("linearGradient", { "id": chrome, "x1": "0", "y1": "0", "x2": "1", "y2": "0" }, [h("stop", { "offset": "0%", "stop-color": "#8d8d8d" }, []), h("stop", { "offset": "24%", "stop-color": "#f8f8f8" }, []), h("stop", { "offset": "48%", "stop-color": "#b9b9b9" }, []), h("stop", { "offset": "74%", "stop-color": "#f3f3f3" }, []), h("stop", { "offset": "100%", "stop-color": "#6f6f6f" }, [])]), h("linearGradient", { "id": paper, "x1": "0", "y1": "0", "x2": "0", "y2": "1" }, [h("stop", { "offset": "0%", "stop-color": lit ? '#fff6df' : '#e7dcc8' }, []), h("stop", { "offset": "100%", "stop-color": lit ? '#f0d7a4' : '#d9cdb8' }, [])])]), h("line", { "x1": "100", "y1": "0", "x2": "100", "y2": "124", "stroke": "#1c1c1c", "stroke-width": "2.1" }, []), h("ellipse", { "cx": "142", "cy": "262", "rx": "34", "ry": "7", "fill": "#000", "opacity": "0.08" }, []), h("ellipse", { "cx": "100", "cy": "128", "rx": "14", "ry": "5", "fill": "#f7f7f7" }, []), h("path", { "d": "M86 128 h28 v18 a14 5 0 0 1 -28 0 z", "fill": `url(#${chrome})` }, []), h("rect", { "x": "93", "y": "130", "width": "2.4", "height": "14", "rx": "1", "fill": "#fff", "opacity": "0.85" }, []), h("path", { "d": "M44 172 L78 148 L156 148 L122 172 Z", "fill": "rgba(255,255,255,0.72)", "stroke": "#bdbdbd", "stroke-width": "1.7", "stroke-linejoin": "round" }, []), h("path", { "d": "M122 172 L156 148 L156 224 L122 248 Z", "fill": "rgba(214,214,214,0.55)", "stroke": "#b0b0b0", "stroke-width": "1.7", "stroke-linejoin": "round" }, []), h("path", { "d": "M44 172 H122 V248 H44 Z", "fill": "rgba(255,255,255,0.38)", "stroke": "#c4c4c4", "stroke-width": "1.8", "stroke-linejoin": "round" }, []), h("path", { "d": "M58 184 H108 V232 H58 Z", "fill": `url(#${paper})` }, []), h("g", { "stroke": lit ? '#d9a84c' : '#c9b48a', "stroke-width": "0.9", "opacity": "0.95" }, [[0, 1, 2, 3, 4].map((index) => (h("line", { "key": index, "x1": "58", "y1": 192 + index * 8, "x2": "108", "y2": 192 + index * 8 }, []))), [0, 1, 2, 3, 4, 5].map((index) => (h("line", { "key": `v${index}`, "x1": 66 + index * 8, "y1": "184", "x2": 66 + index * 8, "y2": "232" }, [])))]), h("path", { "d": "M122 190 L146 174 L146 214 L122 230 Z", "fill": lit ? 'rgba(245,214,150,0.72)' : 'rgba(214,204,184,0.45)' }, []), lit && h("ellipse", { "cx": "84", "cy": "222", "rx": "16", "ry": "6", "fill": "#fff6dc", "opacity": "0.75" }, [])]));
}
function Globe({ prefix, lit }: {
    prefix: string;
    lit: boolean;
}) {
    const red = gid(prefix, 'red');
    const amber = gid(prefix, 'amber');
    return (h("g", {}, [h("defs", {}, [h("radialGradient", { "id": red, "cx": "34%", "cy": "30%", "r": "72%" }, [h("stop", { "offset": "0%", "stop-color": "#ff9b90" }, []), h("stop", { "offset": "42%", "stop-color": "#e23a32" }, []), h("stop", { "offset": "100%", "stop-color": "#8c1514" }, [])]), h("radialGradient", { "id": amber, "cx": "46%", "cy": "42%", "r": "68%" }, [h("stop", { "offset": "0%", "stop-color": lit ? '#fff3c8' : '#e4d2ae', "stop-opacity": "0.98" }, []), h("stop", { "offset": "38%", "stop-color": lit ? '#f0c27a' : '#c9a56e', "stop-opacity": "0.82" }, []), h("stop", { "offset": "72%", "stop-color": "#a56b3c", "stop-opacity": "0.78" }, []), h("stop", { "offset": "100%", "stop-color": "#5c3a28", "stop-opacity": "0.92" }, [])])]), h("line", { "x1": "100", "y1": "0", "x2": "100", "y2": "108", "stroke": "#1c1c1c", "stroke-width": "2.1" }, []), h("ellipse", { "cx": "138", "cy": "268", "rx": "52", "ry": "8", "fill": "#000", "opacity": "0.08" }, []), h("circle", { "cx": "100", "cy": "118", "r": "11", "fill": `url(#${red})` }, []), h("ellipse", { "cx": "96", "cy": "114", "rx": "3.2", "ry": "2", "fill": "#fff", "opacity": "0.45" }, []), h("circle", { "cx": "100", "cy": "142", "r": "16.5", "fill": `url(#${red})` }, []), h("ellipse", { "cx": "94", "cy": "136", "rx": "4.4", "ry": "2.6", "fill": "#fff", "opacity": "0.35" }, []), h("ellipse", { "cx": "100", "cy": "198", "rx": "74", "ry": "52", "fill": `url(#${amber})` }, []), h("ellipse", { "cx": "68", "cy": "176", "rx": "16", "ry": "24", "fill": "#fff", "opacity": "0.18", "transform": "rotate(-16 68 176)" }, []), h("ellipse", { "cx": "100", "cy": "214", "rx": "48", "ry": "22", "fill": lit ? '#ffe7ad' : '#d7c09a', "opacity": lit ? 0.72 : 0.28 }, []), h("ellipse", { "cx": "100", "cy": "228", "rx": "58", "ry": "16", "fill": "none", "stroke": "rgba(255,255,255,0.35)", "stroke-width": "1.5" }, [])]));
}
function Cone({ prefix, lit }: {
    prefix: string;
    lit: boolean;
}) {
    const red = gid(prefix, 'red');
    const cone = gid(prefix, 'cone');
    return (h("g", {}, [h("defs", {}, [h("radialGradient", { "id": red, "cx": "34%", "cy": "30%", "r": "72%" }, [h("stop", { "offset": "0%", "stop-color": "#ff9b90" }, []), h("stop", { "offset": "42%", "stop-color": "#e23a32" }, []), h("stop", { "offset": "100%", "stop-color": "#8c1514" }, [])]), h("linearGradient", { "id": cone, "x1": "0", "y1": "0", "x2": "0", "y2": "1" }, [h("stop", { "offset": "0%", "stop-color": "#fff" }, []), h("stop", { "offset": "70%", "stop-color": "#f7f4ef" }, []), h("stop", { "offset": "100%", "stop-color": "#e7e1d8" }, [])])]), h("line", { "x1": "100", "y1": "0", "x2": "100", "y2": "112", "stroke": "#d8d8d8", "stroke-width": "2.2" }, []), h("line", { "x1": "99", "y1": "0", "x2": "99", "y2": "112", "stroke": "#f7f7f7", "stroke-width": "0.8" }, []), h("ellipse", { "cx": "136", "cy": "246", "rx": "52", "ry": "8", "fill": "#000", "opacity": "0.07" }, []), h("circle", { "cx": "100", "cy": "126", "r": "14", "fill": `url(#${red})` }, []), h("ellipse", { "cx": "94", "cy": "120", "rx": "4", "ry": "2.4", "fill": "#fff", "opacity": "0.4" }, []), h("path", { "d": "M86 142 C84 166 42 190 20 208 C68 222 132 222 180 208 C158 190 116 166 114 142 Z", "fill": `url(#${cone})` }, []), h("ellipse", { "cx": "100", "cy": "208", "rx": "80", "ry": "14", "fill": "#f3eee6" }, []), h("ellipse", { "cx": "100", "cy": "208", "rx": "46", "ry": "8", "fill": lit ? '#fff6e4' : '#ebe4da' }, []), h("circle", { "cx": "100", "cy": "222", "r": "15", "fill": lit ? '#fffdf8' : '#e6e1d8' }, []), h("circle", { "cx": "100", "cy": "222", "r": "8", "fill": lit ? '#fff' : '#ddd6cc', "opacity": lit ? 1 : 0.7 }, []), lit && h("ellipse", { "cx": "94", "cy": "216", "rx": "4", "ry": "2.4", "fill": "#fff", "opacity": "0.9" }, [])]));
}
const PendantLamp = defineComponent({
    props: {
        id: { type: String as PropType<LampId>, required: true },
        lit: { type: Boolean, required: true },
        className: {type: String, default: undefined},
        hanging: { type: Boolean, default: false },
    },
    setup(props: LampProps) {
        const prefix = useId().replace(/:/g, "").replace(/:/g, '');
        return () => {
        const { id, lit, className, hanging = false } = props;
        const hang = LAMP_HANG[id];
        const span = 300 - hang.top;
        const viewBox = hanging ? `0 ${hang.top} 200 ${span}` : '0 0 200 300';
return (h("svg", { "class": className, "viewBox": viewBox, "overflow": "hidden", "aria-hidden": "true", "focusable": "false", "style": hanging ? { width: '104px', height: `${104 * span / 200}px` } : undefined }, [id === 'shade' && h(Shade, { "prefix": prefix, "lit": lit }, () => []), id === 'cube' && h(Cube, { "prefix": prefix, "lit": lit }, () => []), id === 'globe' && h(Globe, { "prefix": prefix, "lit": lit }, () => []), id === 'cone' && h(Cone, { "prefix": prefix, "lit": lit }, () => [])])); };
    }
});

export default PendantLamp

</script>