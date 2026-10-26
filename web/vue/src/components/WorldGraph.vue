<script setup lang="ts">
import { computed, onMounted, onScopeDispose, ref, watch } from 'vue';
import * as echarts from 'echarts/core';
import { GraphChart } from 'echarts/charts';
import { TooltipComponent, LegendComponent } from 'echarts/components';
import { SVGRenderer } from 'echarts/renderers';
import { api } from '../../../src/lib/api';
import { formatApiError } from '../../../src/lib/apiError';
import { MAX_GRAPH_NODES, toEchartsOption } from '../../../src/lib/graph';
import type { WorldGraphResponse } from '../../../src/types';
import styles from '../../../src/components/WorldGraph.module.css';
echarts.use([GraphChart, TooltipComponent, LegendComponent, SVGRenderer]);
const props = defineProps<{
    projectId: string;
}>();
const canvas = ref<HTMLDivElement | null>(null), graph = ref<WorldGraphResponse | null>(null), clipped = ref(0), error = ref<string | null>(null);
const empty = computed(() => graph.value !== null && graph.value.nodes.length === 0);
let generation = 0, chart: ReturnType<typeof echarts.init> | null = null, observer: ResizeObserver | null = null;
function dispose() { generation++; observer?.disconnect(); chart?.dispose(); observer = null; chart = null; }
async function load() {
    dispose();
    const id = generation;
    graph.value = null;
    error.value = null;
    clipped.value = 0;
    if (!canvas.value)
        return;
    const current = echarts.init(canvas.value);
    chart = current;
    observer = new ResizeObserver(() => current.resize());
    observer.observe(canvas.value);
    try {
        const g = await api.listGraph(props.projectId);
        if (id !== generation)
            return;
        graph.value = g;
        clipped.value = Math.max(0, g.nodes.length - MAX_GRAPH_NODES);
        if (g.nodes.length)
            current.setOption(toEchartsOption(g));
    }
    catch (err) {
        if (id === generation)
            error.value = formatApiError(err, '关系图谱加载失败');
    }
}
onMounted(load);
watch(() => props.projectId, load);
onScopeDispose(dispose);
</script>
<template><div :class="styles.wrap"><div v-if="error" class="banner banner-error" role="alert">{{ error }}</div><div v-if="empty" class="empty">暂无关系与设定数据。写作中出现人物关系 / 地点层级 / 设定实体后自动生成世界拓扑。</div><div ref="canvas" :class="empty || error?styles.hidden:styles.canvas" /><p v-if="clipped>0" :class="styles.hint">节点超过 {{ MAX_GRAPH_NODES }} 个，已截断 {{ clipped }} 个（仅展示最核心设定）。</p></div></template>
