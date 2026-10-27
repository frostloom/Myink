import { computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';

/** Lists keep committed filters and pagination in the URL, including browser back. */
export function useAdminListNavigation<T extends Record<string, string>>(defaults: T) {
    const route = useRoute();
    const router = useRouter();
    const filters = computed(() => Object.fromEntries(Object.entries(defaults).map(([key, fallback]) => [key, typeof route.query[key] === 'string' ? route.query[key] : fallback])) as T);
    const offset = computed(() => {
        const value = Number(route.query.offset);
        return Number.isSafeInteger(value) && value >= 0 ? value : 0;
    });
    const setFilters = (value: T) => { void router.replace({ query: { ...route.query, ...value, offset: undefined } }); };
    const setOffset = (value: number) => { void router.replace({ query: { ...route.query, offset: value || undefined } }); };
    const openDetail = (path: string) => router.push({ path, query: { returnTo: route.fullPath } });
    return { filters, offset, setFilters, setOffset, openDetail };
}

/** Only local admin destinations may be used by a copied detail link. */
export function adminReturnTo(value: unknown, tab: string): string {
    return typeof value === 'string' && /^\/admin(?:\?|\/[a-z][a-z0-9-]*(?:\/[^/?#]+)*\??)/i.test(value)
        && !value.includes('\\') && !value.includes('#') ? value : `/admin?tab=${tab}`;
}
