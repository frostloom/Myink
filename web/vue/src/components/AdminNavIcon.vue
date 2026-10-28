<script setup lang="ts">
withDefaults(defineProps<{ name: string; size?: number }>(), { size: 19 })
const paths: Record<string, string> = {
  overview: 'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
  analytics: 'M4 20V10 M10 20V4 M16 20v-7 M22 20H2',
  users: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M16 4a4 4 0 0 1 0 8 M22 21v-2a4 4 0 0 0-3-3.87 M9 3a4 4 0 1 0 0 8a4 4 0 0 0 0-8',
  projects: 'M4 4h6a3 3 0 0 1 3 3v14a4 4 0 0 0-3-2H4z M13 7a3 3 0 0 1 3-3h5v15h-5a4 4 0 0 0-3 2',
  tasks: 'M3 5h3v3H3z M10 6h11 M3 11h3v3H3z M10 12h11 M3 17h3v3H3z M10 18h11',
  runs: 'M3 12h4l3-8 4 16 3-8h4',
  logs: 'M14 2H5v20h14V7z M14 2v6h5 M8 12h8 M8 16h8',
  invites: 'M3 6h18v4a2 2 0 0 0 0 4v4H3v-4a2 2 0 0 0 0-4z M14 6v3 M14 12v1 M14 16v2',
  feedback: 'M21 11a8 8 0 0 1-8 8H8l-5 3v-8a8 8 0 0 1 8-8h2a8 8 0 0 1 8 5 M7 10h10 M7 14h6',
  models: 'm12 3 9 5-9 5-9-5z M3 12l9 5 9-5 M3 16l9 5 9-5',
  routes: 'M5 3v5a4 4 0 0 0 4 4h6a4 4 0 0 1 4 4v5 M5 12v9 M2 18l3 3 3-3 M16 18l3 3 3-3 M2 6l3-3 3 3',
  resources: 'M3 7V4h7l2 3h9v13H3z M7 12h10 M7 16h6',
  defaults: 'M4 4v6 M4 14v6 M12 4v10 M12 18v2 M20 4v2 M20 10v10 M1 10h6 M9 14h6 M17 6h6',
  account: 'm12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6z M8 12l3 3 5-6',
  logout: 'M9 3H3v18h6 M9 12h12 M17 8l4 4-4 4',
  menu: 'M4 6h16 M4 12h16 M4 18h16',
  crown: 'm3 6 4 4 5-7 5 7 4-4-2 12H5z M5 21h14',
}
</script>

<template>
  <svg :width="size" :height="size" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
    <path :d="paths[name] ?? paths.models" />
  </svg>
</template>
