import type { Project } from '../types'

type Listener = { active: boolean; applied: number; update: (projects: Project[]) => void }
const listeners = new Set<Listener>()
let sequence = 0

/** Observe successful lists without retaining account data in a module cache. */
export function subscribeProjectLists(update: (projects: Project[]) => void) {
  const listener = { active: true, applied: 0, update }
  listeners.add(listener)
  return () => { listener.active = false; listeners.delete(listener) }
}

export async function publishProjectList(request: Promise<Project[]>): Promise<Project[]> {
  const recipients = [...listeners]
  const id = ++sequence
  const projects = await request
  for (const listener of recipients) {
    if (!listener.active || id < listener.applied) continue
    listener.applied = id
    listener.update(projects)
  }
  return projects
}
