<script setup lang="ts">
import { computed, onScopeDispose, ref, watch } from 'vue';
import { RouterLink, useRoute } from 'vue-router';
import ProjectRail from '../components/ProjectRail.vue';
import WorldGraph from '../components/WorldGraph.vue';
import { api } from '../../../src/lib/api';
import { formatApiError } from '../../../src/lib/apiError';
import { chapterStatusLabel } from '../../../src/lib/labels';
import type { BookOutline, ChapterMeta, CharacterCard, CharacterStateChange, Foreshadow, LoreEntity, Project, StoryEvent, WorldView } from '../../../src/types';
import styles from '../../../src/pages/LorePage.module.css';
const ENTITY_TYPE_LABELS: Record<string, string> = {
    item: '物品/武器',
    skill: '功法/技能',
    location: '地点',
};
const ENTITY_TYPE_ORDER = ['item', 'skill', 'location'];
// 人物卡片基础属性中文标签（character_card payload 的 identity/role/importance）
const BASE_ATTR_LABELS: Record<string, string> = {
    identity: '身份',
    role: '角色定位',
    importance: '重要性',
};
// 当前状态台账字段中文标签（character_states.field 枚举：realm/injury/goal/knowledge 等 9 类）
const STATE_LABELS: Record<string, string> = {
    realm: '修为',
    power: '实力',
    injury: '伤势',
    goal: '目标',
    location: '位置',
    item: '随身物品',
    knowledge: '已知信息',
    identity: '身份',
    alive: '生死',
};
// 伏笔状态机中文标签（§7.9：planted/developing/resolved/dropped）
const FORESHADOW_STATUS_LABELS: Record<string, string> = {
    planted: '种植中',
    developing: '推进中',
    resolved: '已回收',
    dropped: '已废弃',
};
const FORESHADOW_STATUS_ORDER = ['planted', 'developing', 'resolved', 'dropped'];
const route = useRoute(), projectId = computed(() => String(route.params.projectId ?? ''));
const projects = ref<Project[]>([]), world = ref<WorldView | null>(null), characters = ref<CharacterCard[]>([]), entities = ref<LoreEntity[]>([]), foreshadows = ref<Foreshadow[]>([]), chapters = ref<ChapterMeta[]>([]), events = ref<StoryEvent[]>([]), outline = ref<BookOutline | null>(null), expanded = ref(new Set<string>()), banner = ref<string | null>(null);
const history = ref<Record<string, CharacterStateChange[] | null>>({}), historyError = ref<Record<string, string>>({});
const orderedChapters = computed(() => [...chapters.value].sort((a, b) => b.chapter_seq - a.chapter_seq));
const orderedForeshadows = computed(() => FORESHADOW_STATUS_ORDER.flatMap(status => foreshadows.value.filter(f => f.status === status)));
const realms = computed(() => Array.isArray(world.value?.world_rules.realm_order) ? world.value.world_rules.realm_order.map(String).filter(Boolean) : []);
const rules = computed(() => Object.entries(world.value?.world_rules ?? {}).filter(([key]) => key !== 'realm_order'));
const loading = ref(true);
let generation = 0;
async function load() {
    const id = ++generation, pid = projectId.value;
    loading.value = true;
    banner.value = null;
    world.value = null;
    characters.value = [];
    entities.value = [];
    foreshadows.value = [];
    chapters.value = [];
    events.value = [];
    outline.value = null;
    expanded.value = new Set();
    history.value = {};
    historyError.value = {};
    try {
        const [proj, w, ch, ent, fo, chaps, ol, ev] = await Promise.all([api.listProjects(), api.getWorld(pid), api.getCharacters(pid), api.listEntities(pid), api.listForeshadows(pid), api.listChapters(pid), api.getOutline(pid), api.listEvents(pid)]);
        if (id !== generation)
            return;
        projects.value = proj;
        world.value = w;
        characters.value = ch;
        entities.value = ent;
        foreshadows.value = fo;
        chapters.value = chaps;
        outline.value = ol.outline;
        events.value = ev;
    }
    catch (err) {
        if (id === generation)
            banner.value = formatApiError(err, '设定加载失败');
    } finally { if (id === generation) loading.value = false; }
}
watch(projectId, () => { void load(); }, { immediate: true });
onScopeDispose(() => { generation++; });
async function loadHistory(card: CharacterCard) {
    if (history.value[card.id] === null) return;
    history.value[card.id] = null;
    delete historyError.value[card.id];
    const id = generation;
    try {
        const rows = await api.getCharacterStateHistory(projectId.value, card.id);
        if (id === generation) history.value[card.id] = rows;
    } catch (err) {
        if (id === generation) {
            history.value[card.id] = [];
            historyError.value[card.id] = formatApiError(err, '状态变化加载失败');
        }
    }
}
function toggle(card: CharacterCard) {
    if (expanded.value.has(card.id)) { expanded.value.delete(card.id); return; }
    expanded.value.add(card.id);
    if (!Object.hasOwn(history.value, card.id) || historyError.value[card.id]) void loadHistory(card);
}
function display(value: unknown) { return typeof value === 'object' ? JSON.stringify(value) : String(value); }
</script>
<template>
<div :class="styles.wrap">
<ProjectRail :projects="projects" /><main :class="styles.main">
<div :class="styles.inner">
<header :class="styles.header"><div><h1>设定</h1><div :class="styles.crumb"><RouterLink :to="`/projects/${projectId}`">返回工作台</RouterLink></div></div></header><div v-if="banner" class="banner banner-error" role="alert">{{ banner }} <button type="button" class="btn btn-secondary" @click="load">重新加载设定</button></div><div v-if="loading" class="empty" role="status">加载中…</div>
<template v-if="!loading && !banner">
<section :class="['panel',styles.section]"><h2 :class="styles.sectionTitle">整书大纲</h2><div v-if="outline==null" class="empty">暂无大纲。可在「新建作品」第 ③ 步规划整书卷与阶段。</div><div v-else><template v-if="outline.objective"><span :class="styles.cardLabel">全书 Objective（终局）</span><p :class="styles.entityDesc">{{ outline.objective }}</p></template><div v-if="!outline.volumes.length" class="empty">大纲暂无卷。</div><div v-else :class="styles.outlineStack"><details v-for="(v,vi) in outline.volumes" :key="vi" :class="styles.volumeFold"><summary :class="styles.foldSummary"><span :class="styles.foldTitle">第 {{ v.volume_seq??vi+1 }} 卷大纲{{ v.title?` · ${v.title}`:'' }}</span><span :class="styles.foldMeta">{{ v.chapter_start && v.chapter_end?`第 ${v.chapter_start}–${v.chapter_end} 章`:'章区间未定' }}{{ v.stages?.length?` · ${v.stages.length} 段`:'' }}</span></summary><div :class="styles.foldBody"><span v-if="v.theme" class="badge">{{ v.theme }}</span><span v-if="v.goal" :class="styles.entityDesc">卷目标：{{ v.goal }}</span><ul v-if="v.key_results?.length" :class="styles.constraintList"><li v-for="(k,i) in v.key_results" :key="i">KR：{{ k }}</li></ul><span v-if="v.end_event" :class="styles.entityDesc">卷末事件：{{ v.end_event }}</span><div v-if="!v.stages?.length" class="empty">本卷暂无阶段。</div><details v-for="(s,si) in v.stages" :key="s.stage_seq??si" :class="styles.stageFold"><summary :class="styles.foldSummary"><span :class="styles.foldTitle">{{ s.name||`第 ${si+1} 段` }}</span><span :class="styles.foldMeta">{{ s.chapter_start && s.chapter_end?`第 ${s.chapter_start}–${s.chapter_end} 章`:'章区间未定' }}</span></summary><p v-if="s.goal" :class="[styles.entityDesc,styles.foldBody]">{{ s.goal }}</p></details></div></details></div></div></section>
<section :class="['panel',styles.section]"><h2 :class="styles.sectionTitle">人物卡片</h2><div v-if="!characters.length" class="empty">暂无人物。可在「新建作品」设定或后续章节抽取中建立。</div><div v-else :class="styles.cardGrid"><article v-for="card in characters" :key="card.id" :class="['panel',styles.card]"><button type="button" :class="styles.cardHead" @click="toggle(card)"><span :class="styles.cardName">{{ card.name }}</span><span :class="card.realm_cap==='无'?'badge':'badge badge-accent'">{{ card.realm_cap }}</span><span v-if="card.race" class="badge">{{ card.race }}</span><span :class="styles.cardArrow">{{ expanded.has(card.id)?'▾':'▸' }}</span></button><div v-if="expanded.has(card.id)" :class="styles.cardBody"><dl :class="styles.cardMeta"><template v-if="card.origin"><dt>出身</dt><dd>{{ card.origin }}</dd></template><template v-if="card.personality"><dt>性格</dt><dd>{{ card.personality }}</dd></template></dl><template v-if="Object.keys(card.base_attrs).length"><span :class="styles.cardLabel">基础属性</span><dl :class="styles.cardMeta"><template v-for="(v,k) in card.base_attrs" :key="k"><dt>{{ BASE_ATTR_LABELS[k]??k }}</dt><dd>{{ display(v) }}</dd></template></dl></template><span :class="styles.cardLabel">当前状态</span><div v-if="!Object.keys(card.state).length" class="empty">暂无状态记录。</div><dl v-else :class="styles.cardMeta"><template v-for="(v,k) in card.state" :key="k"><dt>{{ STATE_LABELS[k]??k }}</dt><dd>{{ v }}</dd></template></dl><span :class="styles.cardLabel">状态变化</span><div v-if="historyError[card.id]" class="banner banner-error" role="alert">{{ historyError[card.id] }} <button type="button" class="btn btn-secondary" @click="loadHistory(card)">重试状态变化</button></div><div v-else-if="history[card.id]==null" class="empty">加载中…</div><div v-else-if="!history[card.id]?.length" class="empty">暂无状态变化记录。</div><ol v-else :class="styles.flow"><li v-for="(h,i) in history[card.id]" :key="`${h.field}-${h.chapter_seq}-${i}`" :class="styles.step"><span :class="h.valid_to==null?styles.dotLive:styles.dot" /><div :class="styles.stepMain"><span :class="styles.stepHead"><strong>{{ STATE_LABELS[h.field]??h.field }}</strong><span>第 {{ h.source_chapter }} 章</span></span><span :class="styles.stepChange">{{ h.old_value?`${h.old_value} → ${h.new_value??'—'}`:h.new_value??'—' }}</span></div></li></ol></div></article></div></section>
<section :class="['panel',styles.section]"><h2 :class="styles.sectionTitle">章节记忆</h2><div v-if="!chapters.length" class="empty">暂无已写章节。开始写作后各章摘要自动沉淀于此。</div><ul v-else :class="styles.entityList"><li v-for="c in orderedChapters" :key="c.id" :class="styles.entityItem"><span :class="styles.entityHead"><span :class="styles.entityName">第 {{ c.chapter_seq }} 章</span><span class="badge">{{ chapterStatusLabel(c.status) }}</span><span v-if="c.word_count!=null" :class="styles.entityDesc">{{ c.word_count }} 字</span></span><span :class="styles.entityDesc">{{ c.summary||'（本章暂无摘要）' }}</span></li></ul></section>
<section :class="['panel',styles.section]"><h2 :class="styles.sectionTitle">事件台账</h2><div v-if="!events.length" class="empty">暂无事件。写作后各章抽取的事件自动落此台账。</div><ul v-else :class="styles.entityList"><li v-for="e in events" :key="e.id" :class="styles.entityItem"><span :class="styles.entityHead"><span :class="styles.entityName">第 {{ e.source_chapter }} 章</span><span v-if="e.participants.length" :class="styles.entityDesc">{{ e.participants.join('、') }}</span></span><span :class="styles.entityDesc">{{ e.summary }}</span></li></ul></section>
<section :class="['panel',styles.section]"><h2 :class="styles.sectionTitle">关系图谱</h2><WorldGraph :project-id="projectId" /></section>
<section :class="['panel',styles.section]"><h2 :class="styles.sectionTitle">设定实体</h2><div v-if="!entities.length" class="empty">暂无设定实体。写作中出现新武器 / 功法 / 技能 / 地点时自动登记。</div><div v-else :class="styles.twoCol"><div v-for="t in ENTITY_TYPE_ORDER" :key="t"><h3 :class="styles.subTitle">{{ ENTITY_TYPE_LABELS[t]??t }}</h3><div v-if="!entities.some(e=>e.entity_type===t)" class="empty">暂无</div><ul v-else :class="styles.entityList"><li v-for="e in entities.filter(e=>e.entity_type===t)" :key="e.id" :class="styles.entityItem"><span :class="styles.entityHead"><span :class="styles.entityName">{{ e.name }}</span><span v-if="e.first_seen_chapter!=null" class="badge">第 {{ e.first_seen_chapter }} 章</span></span><span v-if="e.description" :class="styles.entityDesc">{{ e.description }}</span></li></ul></div></div></section>
<section :class="['panel',styles.section]"><h2 :class="styles.sectionTitle">伏笔池</h2><div v-if="!foreshadows.length" class="empty">暂无伏笔。正文中出现可回收的悬念/物件/承诺时自动登记。</div><ul v-else :class="styles.entityList"><li v-for="f in orderedForeshadows" :key="f.id" :class="styles.entityItem"><span :class="styles.entityHead"><span class="badge badge-accent">{{ FORESHADOW_STATUS_LABELS[f.status]??f.status }}</span><span :class="styles.entityName">第 {{ f.planted_chapter }} 章</span><span v-if="f.resolved_chapter!=null" :class="styles.entityDesc">→ 第 {{ f.resolved_chapter }} 章回收</span></span><span :class="styles.entityDesc">{{ f.description }}</span></li></ul></section>
<template v-if="world">
<section :class="['panel',styles.section]"><h2 :class="styles.sectionTitle">世界观</h2><div v-if="realms.length" :class="styles.realmOrder"><span v-for="(r,i) in realms" :key="i" :class="styles.realmStep"><span :class="styles.realmItem">{{ r }}</span><span v-if="i<realms.length-1" :class="styles.realmArrow">→</span></span></div><div v-if="!rules.length" class="empty">暂无世界观规则。</div><dl v-else :class="styles.ruleList"><div v-for="[k,v] in rules" :key="k" :class="styles.ruleRow"><dt :class="styles.ruleKey">{{ k }}</dt><dd :class="styles.ruleVal">{{ display(v) }}</dd></div></dl></section>
<section :class="['panel',styles.section]"><h2 :class="styles.sectionTitle">硬约束</h2><div v-if="!world.hard_constraints.length" class="empty">暂无硬约束。</div><ul v-else :class="styles.constraintList"><li v-for="(c,i) in world.hard_constraints" :key="i">{{ c }}</li></ul></section>
<section :class="['panel',styles.section]"><h2 :class="styles.sectionTitle">势力与地点</h2><div :class="styles.twoCol"><div><h3 :class="styles.subTitle">势力</h3><div v-if="!world.factions.length" class="empty">暂无势力。</div><ul v-else :class="styles.factionList"><li v-for="f in world.factions" :key="f.name"><span :class="styles.factionName">{{ f.name }}</span><span v-if="f.stance" :class="styles.factionStance">{{ f.stance }}</span><span v-if="f.resources.length" :class="styles.factionResources">资源：{{ f.resources.join('、') }}</span></li></ul></div><div><h3 :class="styles.subTitle">地点</h3><div v-if="!world.locations.length" class="empty">暂无地点。</div><ul v-else :class="styles.locationList"><li v-for="l in world.locations" :key="l.name">{{ l.name }}</li></ul></div></div></section>
</template>
</template>
</div>
</main>
</div>
</template>
