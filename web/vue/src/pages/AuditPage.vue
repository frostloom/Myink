<script setup lang="ts">
import { computed, onScopeDispose, ref, watch } from 'vue';
import { RouterLink, useRoute, useRouter } from 'vue-router';
import FindingsList from '../components/FindingsList.vue';
import ProjectRail from '../components/ProjectRail.vue';
import StatusBadge from '../components/StatusBadge.vue';
import { api, ApiError } from '../../../src/lib/api';
import { formatApiError } from '../../../src/lib/apiError';
import type { GlobalAuditReportDetail, GlobalAuditReportSummary, Project } from '../../../src/types';
import styles from '../../../src/pages/AuditPage.module.css';
const route = useRoute(), router = useRouter(), projectId = computed(() => String(route.params.projectId ?? ''));
const projects = ref<Project[]>([]), reports = ref<GlobalAuditReportSummary[] | null>(null), detail = ref<GlobalAuditReportDetail | null>(null), openId = ref<string | null>(null), busy = ref(false), banner = ref<string | null>(null), ok = ref<string | null>(null);
let generation = 0, detailVersion = 0;
async function load(id = generation): Promise<GlobalAuditReportSummary[] | null> { banner.value = null; try {
    const [list, proj] = await Promise.all([api.listGlobalAudits(projectId.value), api.listProjects()]);
    if (id !== generation)
        return null;
    reports.value = list;
    projects.value = proj;
    return list;
}
catch (err) {
    if (id === generation)
        banner.value = formatApiError(err, '报告加载失败');
    return null;
} }
watch(projectId, () => { const id = ++generation; detailVersion++; reports.value = null; detail.value = null; openId.value = null; busy.value = false; banner.value = null; ok.value = null; void load(id); }, { immediate: true });
onScopeDispose(() => { generation++; detailVersion++; });
async function openReport(reportId: string, id = generation) { const request = ++detailVersion; banner.value = null; try {
    const d = await api.getGlobalAudit(projectId.value, reportId);
    if (id !== generation || request !== detailVersion)
        return;
    detail.value = d;
    openId.value = reportId;
}
catch (err) {
    if (id === generation && request === detailVersion)
        banner.value = formatApiError(err, '报告详情加载失败');
} }
function toggle(reportId: string) { if (openId.value === reportId) {
    detailVersion++;
    openId.value = null;
}
else
    void openReport(reportId); }
async function trigger() { if (busy.value)
    return; const id = generation; busy.value = true; banner.value = null; ok.value = null; try {
    await api.triggerGlobalAudit(projectId.value);
    if (id !== generation)
        return;
    const list = await load(id);
    if (id !== generation)
        return;
    const newest = list?.[0];
    if (newest)
        await openReport(newest.report_id, id);
    if (id === generation)
        ok.value = '审计已完成';
}
catch (err) {
    if (id !== generation)
        return;
    if (err instanceof ApiError) {
        if (err.status === 400)
            banner.value = '该书尚无已写章节，无法审计';
        else if (err.status === 502) {
            await load(id);
            if (id === generation)
                banner.value = '审计失败（已落 failed 报告，可查看明细）';
        }
        else
            banner.value = formatApiError(err);
    }
    else
        banner.value = '请求失败，请重试';
}
finally {
    if (id === generation)
        busy.value = false;
} }
function navigateChapter(seq: number) { void router.push(`/projects/${projectId.value}?chapter=${seq}`); }
</script>
<template>
 <div :class="styles.wrap">
<ProjectRail :projects="projects" /><main :class="styles.main">
<div :class="styles.inner">
<header :class="styles.header"><div><h1>全局审计</h1><div :class="styles.crumb"><RouterLink :to="`/projects/${projectId}`">返回工作台</RouterLink><span>每约 30 章对照卷规划，看推进有没有偏离、怎么拉回来</span></div></div><button type="button" class="btn btn-primary" :disabled="busy" @click="trigger">{{ busy?'审计中…':'触发审计' }}</button></header>
 <div v-if="banner" class="banner banner-error" role="alert">{{ banner }}</div><div v-if="ok" class="banner banner-warning" role="status">{{ ok }}</div>
 <div v-if="reports===null" class="empty">加载中…</div><div v-else-if="!reports.length" class="empty">还没有审计报告。写过章节并有整书大纲后，点「触发审计」对照卷规划。</div><ul v-else :class="styles.list"><li v-for="r in reports" :key="r.report_id" :class="['panel',styles.report]"><button type="button" :class="styles.reportHead" @click="toggle(r.report_id)"><StatusBadge :tone="r.status==='completed'?'success':'error'">{{ r.status==='completed'?'完成':'失败' }}</StatusBadge><span :class="styles.window">第 {{ r.window_start }}–{{ r.window_end }} 章</span><span :class="styles.meta">{{ r.chapters }} 章 · 对照 {{ r.sampled }} 个阶段 · {{ r.findings }} 发现{{ r.trigger==='manual'?' · 手动':'' }}</span><span :class="styles.date">{{ r.created_at?.slice(0,16)??'' }}</span></button><div v-if="openId===r.report_id" :class="styles.detail"><div v-if="r.error" class="banner banner-error">失败原因：{{ r.error }}</div><div :class="styles.stats"><span v-for="[label,value] in [['窗口',`${r.window_start}–${r.window_end} 章`],['对照阶段',r.sampled],['findings',r.findings]]" :key="label" :class="styles.stat"><span :class="styles.statLabel">{{ label }}</span><span :class="styles.statValue">{{ value }}</span></span><span v-if="r.volume" :class="styles.dims"><span class="badge badge-accent">{{ r.volume.volumes }} 卷 / {{ r.volume.stages }} 段</span></span></div><FindingsList v-if="detail && detail.report_id===r.report_id" :findings="detail.findings" :on-navigate-chapter="navigateChapter" /></div></li></ul>
 </div>
</main>
</div>
</template>
