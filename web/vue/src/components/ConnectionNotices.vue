<script setup lang="ts">
import { ref, watch } from 'vue';
import styles from '../../../src/components/ConnectionNotices.module.css';
export type ConnectionNotice = {
    id: string;
    tone: 'error' | 'ok';
    text: string;
    returnFocus: HTMLElement | null;
};
const props = defineProps<{
    items: ConnectionNotice[];
}>();
const emit = defineEmits<{
    dismiss: [
        id: string
    ];
}>();
const region = ref<HTMLElement | null>(null);
watch(() => props.items[0], () => { if (region.value)
    region.value.scrollTop = 0; }, { flush: 'post' });
function dismiss(item: ConnectionNotice) { emit('dismiss', item.id); if (item.returnFocus?.isConnected)
    item.returnFocus.focus(); }
</script>
<template>
  <Teleport to="body"><section ref="region" :class="styles.region" aria-label="模型连接通知"><div v-for="item in items" :key="item.id" :class="styles.notice" :data-tone="item.tone" @keydown.esc.stop="dismiss(item)"><div :role="item.tone === 'error' ? 'alert' : 'status'" aria-atomic="true">{{ item.text }}</div><button type="button" class="btn btn-quiet" aria-label="关闭通知" @click="dismiss(item)">关闭</button></div></section></Teleport>
</template>
