import { ref, onScopeDispose } from 'vue'
export function usePrefersReducedMotion() {
 const query = typeof window.matchMedia === 'function' ? window.matchMedia('(prefers-reduced-motion: reduce)') : null
 const still = ref(query?.matches ?? false)
 const sync = () => { still.value = query?.matches ?? false }
 query?.addEventListener('change', sync)
 onScopeDispose(() => query?.removeEventListener('change', sync))
 return still
}
