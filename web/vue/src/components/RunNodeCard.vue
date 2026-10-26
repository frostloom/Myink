<script lang="ts">
import type { PropType } from 'vue'
import { defineComponent, h, computed } from 'vue'

// 执行节点卡：agent_runs 单行快照（node 中文标签 + 模型 + token + 缓存 + 耗时 + 估算成本 + 重试/降级/错误）。
import { nodeLabel, verdictLabel } from "../../../src/lib/labels";
import type { AgentRun } from "../../../src/types";
import styles from "../../../src/components/RunNodeCard.module.css";
export const RunNodeCard = defineComponent({
    name: "RunNodeCard",
    props: { run: { type: Object as PropType<({
        run: AgentRun;
    })["run"]>, required: true } },
    setup(props: {
        run: AgentRun;
    }) {
        const run = computed(() => props.run);
        return () => {
            return (h("div", { "class": styles.card }, [h("header", { "class": styles.head }, [h("span", { "class": styles.node }, [nodeLabel(run.value.node)]), run.value.degraded && h("span", { "class": `badge badge-warning` }, ["降级"]), run.value.retry_count > 0 && (h("span", { "class": `badge badge-minor` }, ["重试 ×", run.value.retry_count])), h("span", { "class": styles.model }, [run.value.model_id ?? '—'])]), h("dl", { "class": styles.meta }, [h("div", { "class": styles.metaItem }, [h("dt", {}, ["入 token"]), h("dd", {}, [run.value.input_tokens])]), h("div", { "class": styles.metaItem }, [h("dt", {}, ["出 token"]), h("dd", {}, [run.value.output_tokens])]), h("div", { "class": styles.metaItem }, [h("dt", {}, ["缓存"]), h("dd", {}, [run.value.cache_hit ? '命中' : '未命中'])]), h("div", { "class": styles.metaItem }, [h("dt", {}, ["耗时"]), h("dd", {}, [run.value.duration_ms, " ms"])]), h("div", { "class": styles.metaItem }, [h("dt", {}, ["估算成本"]), h("dd", {}, ["¥", run.value.cost_est.toFixed(4)])])]), run.value.detail?.audit_verdict && h("div", {}, [h("strong", {}, [run.value.detail.audit_verdict.verdict, " · ", verdictLabel(run.value.detail.audit_verdict.verdict)]), run.value.detail.audit_verdict.reasons?.map((reason, i) => h("p", { "key": i }, [reason]))]), run.value.detail?.route && h("p", {}, ["实际路由：", ({ persist: '进入落库检查', revise: '修订正文并复审', replan_chapter: '重新规划本章', replan_batch: '重新规划批次', needs_review: '暂停，等待人工评审', fail: '失败停止' } as Record<string, string>)[run.value.detail.route] ?? run.value.detail.route, " · 修订 ", run.value.detail.revision_count ?? 0, " 次 · 重规划 ", run.value.detail.replan_count ?? 0, " 次"]), run.value.error && h("p", { "class": styles.error }, ["错误：", run.value.error])]));
        };
    }
});

export default RunNodeCard

</script>
