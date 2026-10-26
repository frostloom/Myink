<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { usePrefersReducedMotion } from '../composables/usePrefersReducedMotion'
import { DEFAULT_WALLPAPER, type WallpaperConfig } from '../../../src/lib/theme'
import styles from '../../../src/components/CanvasMedia.module.css'
const props = withDefaults(defineProps<{ url: string; poster?: string | null; config?: WallpaperConfig }>(), { poster: null, config: () => ({ ...DEFAULT_WALLPAPER }) })
const still = usePrefersReducedMotion()
const video = ref<HTMLVideoElement | null>(null)
watch(still, (value) => {
 if (!video.value) return
 if (value) video.value.pause()
 else void video.value.play()?.catch(() => {})
}, { flush: 'post' })
const frame = computed(() => ({ objectPosition: `${props.config.x}% ${props.config.y}%`, transform: props.config.zoom === 100 ? undefined : `scale(${props.config.zoom / 100})` }))
</script>
<template><div :class="styles.canvas" aria-hidden="true"><img v-if="still && poster" :class="styles.video" :src="poster" alt="" :style="frame" /><video v-else ref="video" :class="styles.video" :src="url" :poster="poster ?? undefined" :autoplay="!still" muted loop playsinline preload="auto" disablepictureinpicture :style="frame" /><span :class="styles.scrim" /></div></template>
