import type { InjectionKey } from 'vue'

/** Pages keep a standalone rail when mounted outside the application shell. */
export const persistentRailKey: InjectionKey<boolean> = Symbol('persistent project navigation')
