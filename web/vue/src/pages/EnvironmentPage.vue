<script setup lang="ts">
import { useMemoryFormGuard } from "../composables/useMemoryFormGuard";
import { computed, onScopeDispose, ref, watch } from 'vue';
import { RouterLink } from 'vue-router';
import ConnectionNotices, { type ConnectionNotice } from '../components/ConnectionNotices.vue';
import ProjectRail from '../components/ProjectRail.vue';
import { useAuth } from '../authContext';
import { api } from '../../../src/lib/api';
import { formatApiError } from '../../../src/lib/apiError';
import type { EnvironmentSettings, Project, RankingsConfig, TaskBudgetLimits, UserDefaults } from '../../../src/types';
import styles from '../../../src/pages/SettingsPage.module.css';
import ui from '../../../src/pages/EnvironmentPage.module.css';
import PageIcon from '../components/AdminNavIcon.vue';
const MODEL_ROLES = [
    { key: 'planner', name: '规划', description: '梳理故事方向与章节计划', label: '规划（planner）' },
    { key: 'writer', name: '写作', description: '生成正文与推进情节', label: '写作（writer）' },
    { key: 'extract', name: '抽取', description: '整理人物、事件与设定', label: '抽取（extract）' },
    { key: 'validator_l2', name: '语义校验', description: '检查前后逻辑与故事一致性', label: '语义校验（validator_l2）' },
    { key: 'audit', name: '审核', description: '检查内容质量与写作约束', label: '审核（audit）' },
    { key: 'summarize', name: '摘要', description: '归纳章节要点与故事进展', label: '摘要（summarize）' },
];
const ROLE_GROUPS = [
    { title: '构思与写作', roles: MODEL_ROLES.slice(0, 2) },
    { title: '检查与审核', roles: MODEL_ROLES.slice(3, 5) },
    { title: '故事记忆', roles: [MODEL_ROLES[2], MODEL_ROLES[5]] },
];
const EMPTY_ROUTE = { value: '', label: '跟随平台默认' };
const DEFAULT_BUDGET: TaskBudgetLimits = { max_requests: 100, max_cost_yuan: 5, max_runtime_seconds: 1800 };
const DEFAULT_RANKINGS: RankingsConfig = { enabled: true, timeout: 10, limit: 10 };
const BUDGET_FIELDS = [
    ['max_requests', '任务请求上限'],
    ['max_cost_yuan', '任务费用上限（元）'],
    ['max_runtime_seconds', '任务运行上限（秒）'],
] as const;
type SectionMsg = {
    tone: 'error' | 'ok';
    text: string;
} | null;
type Preferences = UserDefaults & {
    model_routes: Record<string, string>;
};
type PreferenceUpdate = Parameters<typeof api.updateEnvironment>[0];
type PendingDrafts = {
    original: Preferences;
    draft: Preferences;
    committed: string[];
};
function preserveDrafts<T extends object>(server: T, draft: T, original: T, prefix: string, committed: string[]): T {
    return Object.fromEntries((Object.keys(server) as Array<keyof T>).map((key) => [key,
        draft[key] !== original[key] && !committed.includes(`${prefix}.${String(key)}`) ? draft[key] : server[key],
    ])) as T;
}
function changedFields<T extends object>(draft: T, original: T): Partial<T> {
    return Object.fromEntries((Object.keys(draft) as Array<keyof T>)
        .filter((key) => draft[key] !== original[key])
        .map((key) => [key, draft[key]])) as Partial<T>;
}
const { status, session } = useAuth();
const guest = computed(() => status.value !== 'authenticated');
const projects = ref<Project[]>([]), routeSel = ref<Record<string, string>>({}), availableModels = ref<Array<{
    id: string;
    name: string;
}>>([]);
const loading = ref(true), original = ref<Preferences | null>(null), overriddenFields = ref<string[] | undefined>(), expanded = ref(false);
const taskBudget = ref<TaskBudgetLimits>({ ...DEFAULT_BUDGET }), budgetMessage = ref<SectionMsg>(null), rankings = ref<RankingsConfig>({ ...DEFAULT_RANKINGS }), thinkingEnabled = ref(false), notices = ref<ConnectionNotice[]>([]), rankMsg = ref<SectionMsg>(null), busy = ref<string | null>(null), banner = ref<string | null>(null);
const disabled = computed(() => loading.value || original.value === null || busy.value !== null || guest.value);
useMemoryFormGuard(() => !guest.value && original.value !== null && JSON.stringify({ model_routes: routeSel.value, task_budget: taskBudget.value, rankings: rankings.value, thinking_enabled: thinkingEnabled.value }) !== JSON.stringify(original.value), { recovering: () => guest.value });
let generation = 0;
function notify(id: string, tone: 'error' | 'ok', text: string, returnFocus: HTMLElement | null) { notices.value = [{ id, tone, text, returnFocus }, ...notices.value.filter(item => item.id !== id)]; }
function applyEnvironment(env: EnvironmentSettings, pending?: PendingDrafts) {
    const routes = Object.fromEntries(MODEL_ROLES.map(role => { const value = env.model_routes[role.key] ?? ''; return [role.key, value.startsWith('custom:') ? value : '']; }));
    const preferences = { model_routes: routes, task_budget: env.task_budget ?? { ...DEFAULT_BUDGET }, rankings: env.rankings ?? { ...DEFAULT_RANKINGS }, thinking_enabled: env.thinking_enabled === true };
    original.value = structuredClone(preferences);
    routeSel.value = pending ? preserveDrafts(routes, pending.draft.model_routes, pending.original.model_routes, 'model_routes', pending.committed) : { ...routes };
    taskBudget.value = pending ? preserveDrafts(preferences.task_budget, pending.draft.task_budget, pending.original.task_budget, 'task_budget', pending.committed) : { ...preferences.task_budget };
    rankings.value = pending ? preserveDrafts(preferences.rankings, pending.draft.rankings, pending.original.rankings, 'rankings', pending.committed) : { ...preferences.rankings };
    thinkingEnabled.value = pending && pending.draft.thinking_enabled !== pending.original.thinking_enabled && !pending.committed.includes('thinking_enabled') ? pending.draft.thinking_enabled : preferences.thinking_enabled;
    availableModels.value = env.available_models ?? [];
    overriddenFields.value = env.overridden_fields;
    budgetMessage.value = null;
    rankMsg.value = null;
}
async function load() {
    const id = ++generation;
    banner.value = null;
    original.value = null;
    notices.value = [];
    if (guest.value) {
        loading.value = false;
        return;
    }
    loading.value = true;
    try {
        const [env, proj] = await Promise.all([api.getEnvironment(), api.listProjects()]);
        if (id !== generation)
            return;
        applyEnvironment(env);
        projects.value = proj;
    }
    catch (err) {
        if (id === generation)
            banner.value = formatApiError(err, '高级设置加载失败');
    }
    finally {
        if (id === generation)
            loading.value = false;
    }
}
// A new token for the same owner must not reload and overwrite local edits.
watch([status, () => session.value?.userId], () => { busy.value = null; void load(); }, { immediate: true, flush: 'sync' });
onScopeDispose(() => { generation++; });
function applySavedEnvironment(env: EnvironmentSettings, committed: string[]) { applyEnvironment(env, original.value ? { original: original.value, draft: { model_routes: routeSel.value, task_budget: taskBudget.value, rankings: rankings.value, thinking_enabled: thinkingEnabled.value }, committed } : undefined); }
async function update(key: string, body: PreferenceUpdate, committed: string[], message: string, kind: 'notice' | 'budget' | 'rankings' = 'notice') {
    const id = generation, returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    busy.value = key;
    try {
        const env = await api.updateEnvironment(body);
        if (id !== generation)
            return;
        applySavedEnvironment(env, committed);
        if (kind === 'notice')
            notify(key === 'routes' ? 'save' : 'reset', 'ok', message, returnFocus);
        else if (kind === 'budget')
            budgetMessage.value = { tone: 'ok', text: message };
        else
            rankMsg.value = { tone: 'ok', text: message };
    }
    catch (err) {
        if (id !== generation)
            return;
        const text = formatApiError(err);
        if (kind === 'notice')
            notify(key === 'routes' ? 'save' : 'reset', 'error', text, returnFocus);
        else if (kind === 'budget')
            budgetMessage.value = { tone: 'error', text };
        else
            rankMsg.value = { tone: 'error', text };
    }
    finally {
        if (id === generation)
            busy.value = null;
    }
}
function saveRoutes() { if (disabled.value || !original.value)
    return; const routes = changedFields(routeSel.value, original.value.model_routes), body: PreferenceUpdate = {}; if (Object.keys(routes).length)
    body.model_routes = routes as Record<string, string>; if (thinkingEnabled.value !== original.value.thinking_enabled)
    body.thinking_enabled = thinkingEnabled.value; return update('routes', body, [...Object.keys(routes).map(key => `model_routes.${key}`), ...(body.thinking_enabled !== undefined ? ['thinking_enabled'] : [])], '模型偏好已保存'); }
function saveRankings() { if (disabled.value || !original.value)
    return; if (!Number.isInteger(rankings.value.timeout) || rankings.value.timeout < 1 || rankings.value.timeout > 60) {
    rankMsg.value = { tone: 'error', text: '超时须为 1–60 秒' };
    return;
} if (!Number.isInteger(rankings.value.limit) || rankings.value.limit < 1 || rankings.value.limit > 50) {
    rankMsg.value = { tone: 'error', text: '条数须为 1–50' };
    return;
} rankMsg.value = null; const changes = changedFields(rankings.value, original.value.rankings); return update('rankings', { rankings: changes }, Object.keys(changes).map(key => `rankings.${key}`), '扫榜配置已保存', 'rankings'); }
function saveBudget() { if (disabled.value || !original.value)
    return; const b = taskBudget.value; if (!Number.isSafeInteger(b.max_requests) || b.max_requests < 0 || b.max_requests > 2000000000 || !Number.isSafeInteger(b.max_runtime_seconds) || b.max_runtime_seconds < 0 || b.max_runtime_seconds > 9000000000000 || !Number.isFinite(b.max_cost_yuan) || b.max_cost_yuan < 0 || b.max_cost_yuan > 9000000000000 || Math.abs(b.max_cost_yuan * 1e6 - Math.round(b.max_cost_yuan * 1e6)) > 0.0001) {
    budgetMessage.value = { tone: 'error', text: '预算必须为非负数；请求和秒数为整数，费用最多六位小数。' };
    return;
} budgetMessage.value = null; const changes = changedFields(b, original.value.task_budget); return update('budget', { task_budget: changes }, Object.keys(changes).map(key => `task_budget.${key}`), '已保存，仅影响新任务。', 'budget'); }
function resetPreference(path: string) { if (disabled.value)
    return; return update(path, { reset_preferences: [path] }, [path], '已恢复平台默认'); }
const preferenceFields = computed(() => [
    { path: 'thinking_enabled', label: '思考模式' }, ...MODEL_ROLES.map(role => ({ path: `model_routes.${role.key}`, label: role.label })), ...BUDGET_FIELDS.map(([key, label]) => ({ path: `task_budget.${key}`, label })), { path: 'rankings.enabled', label: '启用扫榜' }, { path: 'rankings.timeout', label: '扫榜超时' }, { path: 'rankings.limit', label: '扫榜条数' }
]);
function labelFor(path: string) { return preferenceFields.value.find(field => field.path === path)?.label ?? path; }
function overrideText(path: string) { return overriddenFields.value === undefined ? '覆盖状态暂不可用' : overriddenFields.value.includes(path) ? '当前使用个人设置' : '当前使用平台默认'; }
</script>
<template>
  <div :class="[styles.wrap, ui.wrap]">
    <ConnectionNotices :items="notices" @dismiss="id => notices = notices.filter(item => item.id !== id)" />
    <ProjectRail :projects="projects" />
    <main :class="[styles.main, ui.main]">
      <div :class="ui.page">
        <header :class="ui.pageHead">
          <div><h1>高级设置</h1><p>调整自己的创作偏好，也可以直接使用平台默认设置。</p></div>
          <RouterLink to="/long" class="btn btn-quiet">返回长篇</RouterLink>
        </header>
        <div v-if="banner" class="banner banner-error" role="alert">{{ banner }}</div>
        <button v-if="banner" class="btn btn-secondary" :disabled="loading || busy !== null" @click="load">重新加载高级设置</button>
        <p v-if="loading" role="status">正在加载高级设置…</p>
        <p v-if="guest" :class="ui.hint">登录后可调整个人偏好。</p>
        <div :class="ui.intro">
          <span :class="ui.introIcon"><PageIcon name="defaults" :size="23" /></span>
          <div><h2>按你的习惯创作</h2><p>模型、任务预算与扫榜配置均可单独调整和保存。</p></div>
          <button class="btn btn-secondary" type="button" :aria-expanded="expanded" aria-controls="advanced-preferences" @click="expanded = !expanded">{{ expanded ? '收起高级设置' : '展开高级设置' }}</button>
        </div>
        <div v-if="expanded" id="advanced-preferences" :class="ui.sections">
          <section :class="ui.section" aria-labelledby="model-preferences">
            <header :class="ui.sectionHead"><PageIcon name="models" :size="21" /><div><h2 id="model-preferences">模型偏好</h2><p>选择管理员开放的模型；未指定时跟随平台默认。保存仅更新已修改的字段。</p></div></header>
            <p v-if="!loading && !availableModels.length" :class="ui.notice">暂无已发布模型，将使用平台默认配置。</p>
            <div :class="[ui.preferenceRow, ui.thinkingRow]">
              <label for="thinking-mode" :class="ui.label"><strong>思考模式</strong><span>按需启用模型的推理能力</span></label>
              <select id="thinking-mode" class="input" aria-label="思考模式" :disabled="disabled" :value="thinkingEnabled ? '1' : '0'" @change="thinkingEnabled = ($event.target as HTMLSelectElement).value === '1'"><option value="0">关闭</option><option value="1">开启</option></select>
              <div :class="ui.source"><span>{{ overrideText('thinking_enabled') }}</span><button type="button" class="btn btn-quiet" aria-label="恢复思考模式默认值" :disabled="disabled || overriddenFields?.includes('thinking_enabled') === false" @click="resetPreference('thinking_enabled')">恢复默认</button></div>
            </div>
            <div :class="ui.columnHead" aria-hidden="true"><span>创作环节</span><span>使用模型</span><span>设置来源</span></div>
            <section v-for="group in ROLE_GROUPS" :key="group.title" :class="ui.roleGroup" :aria-label="group.title">
              <h3>{{ group.title }}</h3>
              <div v-for="role in group.roles" :key="role.key" :class="ui.preferenceRow">
                <label :for="`model-${role.key}`" :class="ui.label"><strong>{{ role.name }}</strong><span>{{ role.description }}</span></label>
                <select :id="`model-${role.key}`" v-model="routeSel[role.key]" class="input" :aria-label="role.label" :disabled="disabled"><option value="">{{ EMPTY_ROUTE.label }}</option><option v-for="model in availableModels" :key="model.id" :value="model.id">{{ model.name }}</option></select>
                <div :class="ui.source"><span>{{ overrideText(`model_routes.${role.key}`) }}</span><button type="button" class="btn btn-quiet" :aria-label="`恢复${role.label}默认值`" :disabled="disabled || overriddenFields?.includes(`model_routes.${role.key}`) === false" @click="resetPreference(`model_routes.${role.key}`)">恢复默认</button></div>
              </div>
            </section>
            <footer :class="ui.saveRow"><span>每个环节都可随时恢复平台默认。</span><button type="button" class="btn btn-primary" :disabled="disabled" @click="saveRoutes">{{ busy === 'routes' ? '保存中…' : '保存模型偏好' }}</button></footer>
          </section>
          <section :class="ui.section" aria-labelledby="task-budget">
            <header :class="ui.sectionHead"><PageIcon name="tasks" :size="21" /><div><h2 id="task-budget">任务总预算</h2><p>同一批次的所有章节共用预算。0 表示不限；修改只影响新任务，仍受平台配额和权限限制。</p></div></header>
            <div :class="ui.fieldGrid">
              <div v-for="[key, label] in BUDGET_FIELDS" :key="key" :class="ui.fieldBlock">
                <label :class="ui.field"><span>{{ label }}</span><input v-model.number="taskBudget[key]" class="input" type="number" min="0" :step="key === 'max_cost_yuan' ? '0.000001' : '1'" :disabled="disabled" /></label>
                <div :class="ui.fieldSource"><span>{{ overrideText(`task_budget.${key}`) }}</span><button type="button" class="btn btn-quiet" :aria-label="`恢复${label}默认值`" :disabled="disabled || overriddenFields?.includes(`task_budget.${key}`) === false" @click="resetPreference(`task_budget.${key}`)">恢复默认</button></div>
              </div>
            </div>
            <footer :class="ui.saveRow"><span v-if="budgetMessage" :role="budgetMessage.tone === 'error' ? 'alert' : 'status'" :class="budgetMessage.tone === 'error' ? ui.error : ui.success">{{ budgetMessage.text }}</span><span v-else>仅影响保存之后创建的新任务。</span><button type="button" class="btn btn-primary" :disabled="disabled" @click="saveBudget">保存任务预算</button></footer>
          </section>
          <section :class="ui.section" aria-labelledby="rankings-settings">
            <header :class="ui.sectionHead"><PageIcon name="analytics" :size="21" /><div><h2 id="rankings-settings">扫榜</h2><p>番茄榜单用于建书前寻找灵感，不写入故事记忆。</p></div></header>
            <div :class="ui.fieldGrid">
              <div :class="ui.fieldBlock"><label :class="ui.field"><span>启用扫榜</span><select class="input" :disabled="disabled" :value="rankings.enabled ? '1' : '0'" @change="rankings.enabled = ($event.target as HTMLSelectElement).value === '1'"><option value="1">开启</option><option value="0">关闭（只用示例数据）</option></select></label><div :class="ui.fieldSource"><span>{{ overrideText('rankings.enabled') }}</span><button type="button" class="btn btn-quiet" aria-label="恢复启用扫榜默认值" :disabled="disabled || overriddenFields?.includes('rankings.enabled') === false" @click="resetPreference('rankings.enabled')">恢复默认</button></div></div>
              <div v-for="[key, label, title, max] in ([['timeout', '扫榜超时', '超时（秒）', 60], ['limit', '扫榜条数', '条数上限', 50]] as const)" :key="key" :class="ui.fieldBlock"><label :class="ui.field"><span>{{ title }}</span><input v-model.number="rankings[key]" class="input" :aria-label="label" type="number" min="1" :max="max" :disabled="disabled" /></label><div :class="ui.fieldSource"><span>{{ overrideText(`rankings.${key}`) }}</span><button type="button" class="btn btn-quiet" :aria-label="`恢复${labelFor(`rankings.${key}`)}默认值`" :disabled="disabled || overriddenFields?.includes(`rankings.${key}`) === false" @click="resetPreference(`rankings.${key}`)">恢复默认</button></div></div>
            </div>
            <footer :class="ui.saveRow"><span v-if="rankMsg" :role="rankMsg.tone === 'error' ? 'alert' : 'status'" :class="rankMsg.tone === 'error' ? ui.error : ui.success">{{ rankMsg.text }}</span><span v-else>可分别调整扫榜开关、超时和条数。</span><button type="button" class="btn btn-primary" :disabled="disabled" @click="saveRankings">{{ busy === 'rankings' ? '保存中…' : '保存扫榜配置' }}</button></footer>
          </section>
        </div>
      </div>
    </main>
  </div>
</template>
