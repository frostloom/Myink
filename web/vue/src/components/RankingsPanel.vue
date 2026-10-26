<script lang="ts">
import { defineComponent, ref, computed, watch, onBeforeUnmount, h } from 'vue';
// 扫榜灵感面板（§10 拉取外部榜单 → 只作建书前的灵感工具）。
// 全局无项目端点：不传 projectId（或建书向导里）→ 展示外部实时榜单，供用户建书前
// 看题材风向；不注入任何生成节点，数据不进记忆/事实层。
// source=remote 显示实时榜单（accent 徽标）；source=sample 显示降级横幅
// （网络不可达 / RANKINGS_ENABLED=0）+ 示例数据（warning 徽标，书名带【示例】前缀）。
// 头部刷新按钮强制绕过进程内 TTL 缓存重拉；数据仅灵感参考，不进记忆/事实层。
import { useAuth } from '../authContext';
import { api } from '../../../src/lib/api';
import { formatApiError } from '../../../src/lib/apiError';
import { hotText, sourceLabel, sourceTone, tagsText } from '../../../src/lib/rankings';
import type { RankingsResponse } from '../../../src/types';
import StatusBadge from './StatusBadge.vue';
import styles from '../../../src/components/RankingsPanel.module.css';
export default defineComponent({
    name: 'RankingsPanel', setup() {
        const { status } = useAuth();
        const guest = computed(() => status.value === 'anonymous');
        const open = ref(false);
        const data = ref<RankingsResponse | null>(null);
        const busy = ref(false);
        const error = ref<string | null>(null);
        let generation = 0;
        let alive = true;
        const active = (attempt: number) => alive && attempt === generation;
        onBeforeUnmount(() => { alive = false; generation++; });
        const load = async (refresh: boolean) => {
            if (guest.value || busy.value) return;
            const attempt = ++generation;
            busy.value = true;
            error.value = null;
            try {
                const next = await api.listRankings(refresh);
                if (active(attempt)) data.value = next;
            } catch (err) {
                if (active(attempt)) error.value = formatApiError(err, '榜单加载失败');
            } finally {
                if (active(attempt)) busy.value = false;
            }
        };
        // Prewarm once for authenticated visitors; a forced refresh supersedes it.
        watch(guest, () => {
            const attempt = ++generation;
            data.value = null;
            busy.value = false;
            error.value = null;
            if (guest.value) return;
            void api.listRankings().then(next => { if (active(attempt)) data.value = next; }).catch(() => {});
        }, { immediate: true });
        const degraded = computed(() => data.value?.source === 'sample');
        return () => { const rankings = data.value; return (h("section", {
            "class": `panel ${styles.panel}`
        }, [
            h("header", {
                "class": styles.head
            }, [
                h("button", {
                    "type": "button", "class": styles.toggle, "onClick": () => open.value = ((o) => !o)(open.value)
                }, [
                    h("span", {
                        "class": styles.title
                    }, ["扫榜灵感"]), h("span", {
                        "class": styles.caret
                    }, [open.value ? '▾' : '▸'])
                ]), h("button", {
                    "type": "button", "class": "btn btn-quiet", "disabled": busy.value, "title": "强制刷新（绕过缓存）", "onClick": () => void load(true)
                }, [busy.value ? '刷新中…' : '刷新'])
            ]), error.value && h("div", {
                "class": "banner banner-error"
            }, [error.value]), open.value && !rankings && !error.value && (h("p", {
                "class": "empty"
            }, ["扫榜灵感为空。建书前看看外部题材风向，给梗概找些参考。"])), open.value && rankings && (h("div", {
                "class": styles.body
            }, [
                degraded.value && (h("div", {
                    "class": "banner banner-warning"
                }, [
                    "外部榜单不可用（", rankings.error ?? '网络不可达或已禁用', "）。下方为内置示例数据，仅示意字段形状；建书不依赖此面板。"
                ])), h("div", {
                    "class": styles.meta
                }, [
                    h(StatusBadge, {
                        "tone": sourceTone(rankings.source)
                    }, () => [sourceLabel(rankings.source)]), rankings.fetched_at && (h("span", {
                        "class": styles.fetched
                    }, [rankings.fetched_at.replace('T', ' ').slice(0, 19)]))
                ]), h("ul", {
                    "class": styles.list
                }, [rankings.items.map((item) => (h("li", {
                        "key": item.rank, "class": styles.item
                    }, [
                        h("span", {
                            "class": styles.rank
                        }, [item.rank]), h("div", {
                            "class": styles.info
                        }, [
                            h("span", {
                                "class": styles.titleText
                            }, [item.title]), item.author && h("span", {
                                "class": styles.author
                            }, [item.author])
                        ]), h("div", {
                            "class": styles.rightMeta
                        }, [
                            tagsText(item.tags) && h("span", {
                                "class": styles.tags
                            }, [tagsText(item.tags)]), hotText(item.hot) && h("span", {
                                "class": styles.hot
                            }, [hotText(item.hot)])
                        ])
                    ])))]), h("p", {
                    "class": styles.note
                }, ["仅作建书前的题材风向参考，禁止抄袭书名/设定，不构成本书事实约束。"])
            ]))
        ]));
        };
    }
});

</script>
