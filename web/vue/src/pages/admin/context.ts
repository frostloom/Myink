import { inject, type InjectionKey } from 'vue';
import type { AdminOutletContext } from './shared';
export const adminContextKey: InjectionKey<AdminOutletContext> = Symbol('administrator');
export function useAdminContext(): AdminOutletContext {
    const context = inject(adminContextKey);
    if (!context)
        throw new Error('Administrator context is missing');
    return context;
}
