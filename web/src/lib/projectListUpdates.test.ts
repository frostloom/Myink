import { expect, it } from 'vitest'
import type { Project } from '../types'
import { publishProjectList, subscribeProjectLists } from './projectListUpdates'

function pending() {
  let resolve!: (projects: Project[]) => void
  const promise = new Promise<Project[]>(done => { resolve = done })
  return { promise, resolve }
}
const books = [{ id: 'a', title: 'A' }] as Project[]

it('publishes successful empty results so deleting the final book clears navigation', async () => {
  let visible: Project[] = []
  const stop = subscribeProjectLists(projects => { visible = projects })
  try {
    await publishProjectList(Promise.resolve(books))
    expect(visible).toEqual(books)
    await publishProjectList(Promise.resolve([]))
    expect(visible).toEqual([])
  } finally { stop() }
})

it('does not publish an old A response into a new A session after A to B to A', async () => {
  const oldA = pending()
  let visible: Project[] = []
  const stopA = subscribeProjectLists(projects => { visible = projects })
  const response = publishProjectList(oldA.promise)
  stopA()
  const stopB = subscribeProjectLists(projects => { visible = projects })
  stopB()
  const stopNewA = subscribeProjectLists(projects => { visible = projects })
  try {
    oldA.resolve(books)
    await response
    expect(visible).toEqual([])
    await publishProjectList(Promise.resolve([{ id: 'new', title: 'New A' }] as Project[]))
    expect(visible[0]?.id).toBe('new')
  } finally { stopNewA() }
})

it('retains the newest completed list when an earlier request arrives later', async () => {
  let visible: Project[] = []
  const stop = subscribeProjectLists(projects => { visible = projects })
  const old = pending()
  try {
    const response = publishProjectList(old.promise)
    await publishProjectList(Promise.resolve([]))
    old.resolve(books)
    await response
    expect(visible).toEqual([])
  } finally { stop() }
})
