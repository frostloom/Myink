<script setup lang="ts">
import { useMemoryFormGuard } from "../composables/useMemoryFormGuard";
import { computed, onScopeDispose, ref, watch } from 'vue';
import { RouterLink, useRoute, useRouter } from 'vue-router';
import ProjectRail from '../components/ProjectRail.vue';
import WritingResourcePicker from '../components/WritingResourcePicker.vue';
import { api } from '../../../src/lib/api';
import { formatApiError } from '../../../src/lib/apiError';
import { isManagedPack, type BookGenrePack } from '../../../src/lib/genrePacks';
import type { Project, ProjectSettings } from '../../../src/types';
import styles from '../../../src/pages/SettingsPage.module.css';
const route = useRoute(), router = useRouter();
const projectId = computed(() => String(route.params.projectId ?? ''));
const navigationState = ref(router.options.history.state);
watch(() => route.fullPath, () => { navigationState.value = router.options.history.state; });
const beforeWriting = computed(() => navigationState.value?.configureBeforeWriting === true);
const planWarning = computed(() => navigationState.value?.planWarning);
const projects = ref<Project[]>([]), settings = ref<ProjectSettings | null>(null), genrePack = ref<BookGenrePack | null>(null), targetWords = ref('3000'), busy = ref<string | null>(null), banner = ref<string | null>(null), ok = ref<string | null>(null);
let version = 0;
useMemoryFormGuard(() => settings.value !== null && targetWords.value !== String(projects.value.find(project => project.id === projectId.value)?.target_words ?? 3000));
async function load(id: number) { if (id !== version)
    return; banner.value = null; const pid = projectId.value; try {
    const [s, proj] = await Promise.all([api.getSettings(pid), api.listProjects()]);
    if (id !== version)
        return;
    settings.value = s;
    genrePack.value = isManagedPack(s.genre_pack) ? s.genre_pack : null;
    projects.value = proj;
    const cur = proj.find(p => p.id === pid);
    targetWords.value = cur?.target_words != null ? String(cur.target_words) : '3000';
}
catch (err) {
    if (id === version)
        banner.value = formatApiError(err, '设置加载失败');
} }
watch(projectId, () => { const id = ++version; settings.value = null; genrePack.value = null; targetWords.value = '3000'; busy.value = null; banner.value = null; ok.value = null; void load(id); }, { immediate: true });
onScopeDispose(() => { version++; });
async function saveTargetWords() { if (!settings.value || busy.value)
    return; const id = version, words = Number(targetWords.value); if (!Number.isInteger(words) || words < 500 || words > 20000) {
    banner.value = '目标字数需为 500–20000 的整数';
    return;
} busy.value = 'words'; banner.value = null; ok.value = null; try {
    await api.updateProject(projectId.value, { target_words: words });
    if (id !== version)
        return;
    await load(id);
    if (id === version)
        ok.value = '目标字数已保存，对新生成章节生效';
}
catch (err) {
    if (id === version) {
        ok.value = null;
        banner.value = formatApiError(err);
    }
}
finally {
    if (id === version)
        busy.value = null;
} }
</script>
<template>
 <div :class="styles.wrap">
<ProjectRail :projects="projects" /><main :class="styles.main">
<div :class="styles.inner">
<header :class="styles.header"><div><h1>创作设置</h1><div :class="styles.crumb"><RouterLink :to="{path: `/projects/${projectId}`, state: {planWarning}}">{{ beforeWriting?'选好后返回工作台开写':'返回工作台' }}</RouterLink><span v-if="settings" class="badge">v{{ settings.version }}</span></div></div><span v-if="genrePack" class="badge badge-accent">{{ genrePack.secondary_name?`${genrePack.source_name}+${genrePack.secondary_name}`:genrePack.source_name }}</span></header>
 <div v-if="banner" class="banner banner-error" role="alert">{{ banner }}</div><div v-if="ok" class="banner banner-warning" role="status">{{ ok }}</div><p v-if="beforeWriting" class="banner">方案已确认，正文尚未开始生成。请勾选需要的资源并保存，再返回工作台点击“开始写”。<span v-if="planWarning">{{ planWarning }}</span></p><WritingResourcePicker :key="projectId" :project-id="projectId" />
 <section :class="['panel',styles.section]"><h2 :class="styles.sectionTitle">本书题材</h2><p :class="styles.hint">以下为建书历史题材；启用写作资源后，当前题材与主辅顺序以「本书写作资源」中已保存的快照为准。</p><template v-if="genrePack"><p :class="styles.hint">根题材：{{ genrePack.source_name }}{{ genrePack.secondary_name?` · 辅题材：${genrePack.secondary_name}`:'' }}</p><p>{{ genrePack.selling_point }}</p><p :class="styles.hint">此处保留建书时的历史快照，不随资源选择更新。</p></template><p v-else :class="styles.hint">本书创建时未选题材包，不回填。新书请在建书页选择。</p></section>
 <section :class="['panel',styles.section]"><h2 :class="styles.sectionTitle">生成设置</h2><label :class="styles.field"><span :class="styles.fieldLabel">每章目标字数（500–20000）</span><input v-model="targetWords" class="input" type="number" min="500" max="20000" step="100" /></label><div :class="styles.saveRow"><button type="button" class="btn btn-primary" :disabled="busy!==null || !settings" @click="saveTargetWords">{{ busy==='words'?'保存中…':'保存目标字数' }}</button><RouterLink class="btn btn-quiet" to="/environment">高级设置</RouterLink></div></section>
 </div>
</main>
</div>
</template>
