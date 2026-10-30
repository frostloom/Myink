<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import AdminNavIcon from '../../components/AdminNavIcon.vue'
import styles from '../../../../src/pages/admin/ModelRouting.module.css'

type Connection = { id: string; name: string; model: string; enabled: boolean; minimum_tier?: 'normal' | 'vip' }
const props = defineProps<{
  roles: Array<{ key: string; label: string }>
  connections: Connection[]
  normalRoutes: Record<string, string>
  vipRoutes: Record<string, string>
  weights: { vip: number; normal: number }
}>()
const emit = defineEmits<{
  'update:normalRoutes': [value: Record<string, string>]
  'update:vipRoutes': [value: Record<string, string>]
  'update:weights': [value: { vip: number; normal: number }]
}>()
const descriptions: Record<string, string> = {
  writer: '正文生成与修订', planner: '大纲与章节计划', validator_l2: '语义与规则校验',
  extract: '事件与记忆提取', audit: '内容审核与一致性检查', summarize: '上下文摘要',
}
const orderedRoles = computed(() => [...props.roles].sort((a, b) => Number(b.key === 'writer') - Number(a.key === 'writer')))
const enabled = computed(() => props.connections.filter(model => model.enabled))
const ordinary = computed(() => enabled.value.filter(model => model.minimum_tier !== 'vip'))
const validWeights = computed(() => Object.values(props.weights).every(weight => Number.isInteger(weight) && weight >= 1 && weight <= 10))
const share = computed(() => validWeights.value ? Math.round(props.weights.vip / (props.weights.vip + props.weights.normal) * 100) : 0)

function effective(role: string, vip = false) {
  const ref = vip
    ? props.vipRoutes[role] || props.normalRoutes[role] || props.vipRoutes.writer || props.normalRoutes.writer
    : props.normalRoutes[role] || props.normalRoutes.writer
  const model = (vip ? enabled.value : ordinary.value).find(item => `custom:${item.id}` === ref)
  return model?.name || (ref ? '原模型已不可用，请重新分配' : '尚未分配模型')
}
function inherited(role: string) {
  if (props.normalRoutes[role]) return `沿用普通用户的${props.roles.find(item => item.key === role)?.label ?? role}分配`
  return props.vipRoutes.writer && role !== 'writer' ? '跟随 VIP 写作模型' : '跟随普通写作模型'
}
function choose(role: string, event: Event, vip = false) {
  const value = (event.target as HTMLSelectElement).value
  const routes = { ...(vip ? props.vipRoutes : props.normalRoutes) }
  if (value) routes[role] = value
  else delete routes[role]
  if (vip) emit('update:vipRoutes', routes)
  else emit('update:normalRoutes', routes)
}
function weight(tier: 'vip' | 'normal', event: Event) {
  emit('update:weights', { ...props.weights, [tier]: Number((event.target as HTMLInputElement).value) })
}
</script>

<template>
  <div :class="styles.board">
    <section :class="styles.matrix" aria-label="会员模型分配">
      <header :class="styles.sectionHead">
        <div><h2>按会员等级分配模型</h2><p>下方预览各环节的平台默认模型，保存后生效。个人选择仍须符合会员权限。</p></div>
        <RouterLink to="/admin/models" :class="styles.manageLink">管理模型库</RouterLink>
      </header>
      <table :class="styles.table" aria-label="普通用户与 VIP 模型对照">
        <thead>
<tr>
          <th scope="col" :class="styles.roleHeading">创作环节</th>
          <th scope="col"><div :class="styles.tierHeading"><AdminNavIcon name="users" /><strong>普通用户</strong><span :class="styles.normalBadge">基础权益</span></div><p>{{ ordinary.length }} 个可分配模型</p></th>
          <th scope="col" :class="styles.vipColumn"><div :class="styles.tierHeading"><AdminNavIcon name="crown" /><strong>VIP 会员</strong><span :class="styles.vipBadge">VIP</span></div><p>可使用基础模型及 VIP 专用模型</p></th>
        </tr>
</thead>
        <tbody>
<tr v-for="role in orderedRoles" :key="role.key" :class="role.key === 'writer' ? styles.writerRow : undefined">
          <th scope="row"><strong>{{ role.label }}</strong><span>{{ descriptions[role.key] }}</span><small v-if="role.key === 'writer'">基础默认</small></th>
          <td data-tier="普通用户">
            <span :class="styles.mobileTier">普通用户</span>
            <select :aria-label="role.label" :value="normalRoutes[role.key] ?? ''" :class="['input', styles.select]" @change="choose(role.key, $event)">
              <option value="">{{ role.key === 'writer' ? '请选择默认写作模型' : '跟随普通写作模型' }}</option>
              <option v-for="model in ordinary" :key="model.id" :value="`custom:${model.id}`">{{ model.name }}</option>
            </select>
            <p :class="styles.effective">默认模型：<strong>{{ effective(role.key) }}</strong></p>
            <span v-if="normalRoutes[role.key] && role.key === 'writer'" :class="styles.inheritance">其他未指定环节的默认模型</span>
          </td>
          <td :class="styles.vipColumn" data-tier="VIP 会员">
            <span :class="styles.mobileTier">VIP 会员</span>
            <select :aria-label="`VIP ${role.label}默认模型`" :value="vipRoutes[role.key] ?? ''" :class="['input', styles.select]" @change="choose(role.key, $event, true)">
              <option value="">{{ inherited(role.key) }}</option>
              <option v-for="model in enabled" :key="model.id" :value="`custom:${model.id}`">{{ model.name }}{{ model.minimum_tier === 'vip' ? ' · 仅 VIP' : '' }}</option>
            </select>
            <p :class="styles.effective">默认模型：<strong>{{ effective(role.key, true) }}</strong></p>
            <span v-if="vipRoutes[role.key]" :class="[styles.inheritance, styles.overridden]">VIP 已单独指定</span>
          </td>
        </tr>
</tbody>
      </table>
      <footer :class="styles.matrixFoot"><AdminNavIcon name="account" :size="16" /><span>普通用户无法调用 VIP 专用模型。模型可用等级在模型库中设置。</span></footer>
    </section>

    <section :class="styles.scheduling" aria-label="任务调度策略">
      <div :class="styles.scheduleIntro">
<div :class="styles.sectionHead"><div><h2>任务调度</h2><p>VIP 优先，普通用户也保留调度机会。</p></div></div>
        <p :class="styles.scheduleCopy">两个队列同时有任务时，按权重轮流取任务。任一队列空闲时，另一方使用空闲份额。</p>
        <p :class="styles.scheduleNote">权重影响取任务的机会，不承诺完成时间，也不会打断已经执行的任务。</p>
      </div>
      <div :class="styles.scheduleControls">
        <div :class="styles.ratio"><span>调度比例预览</span><strong>{{ weights.vip }} <small>:</small> {{ weights.normal }}</strong><span>VIP / 普通用户</span></div>
        <div v-if="validWeights" :class="styles.shareBar" role="img" :aria-label="`VIP ${share}%，普通用户 ${100 - share}% 的调度份额`"><span :style="{ width: `${share}%` }" /><span :style="{ width: `${100 - share}%` }" /></div>
        <div :class="styles.weightFields">
          <label><span><AdminNavIcon name="crown" :size="16" />VIP 调度权重</span><input class="input" type="number" min="1" max="10" step="1" :value="weights.vip" :aria-invalid="!validWeights" aria-describedby="queue-weight-note" @input="weight('vip', $event)" /></label>
          <label><span><AdminNavIcon name="users" :size="16" />普通用户调度权重</span><input class="input" type="number" min="1" max="10" step="1" :value="weights.normal" :aria-invalid="!validWeights" aria-describedby="queue-weight-note" @input="weight('normal', $event)" /></label>
        </div>
        <p id="queue-weight-note" :class="validWeights ? styles.scheduleNote : styles.invalid">{{ validWeights ? '每项为 1–10 的整数，普通用户份额始终大于零。' : '请输入 1–10 的整数权重。' }}</p>
      </div>
    </section>
  </div>
</template>
