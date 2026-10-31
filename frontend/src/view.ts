import { useSyncExternalStore } from 'react'
import type { Project } from './api'

export type View = 'writer' | 'illustrator'
export type Side = 'chat' | 'review' | 'versions'

const listeners = new Set<() => void>()
const changed = () => listeners.forEach((fn) => fn())
const subscribe = (fn: () => void) => {
  listeners.add(fn)
  return () => void listeners.delete(fn)
}
const read = (key: string) => {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}
const write = (key: string, value: string) => {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* private mode: the choice lasts until the page is reloaded only */
  }
  changed()
}

/** The chosen way of working on a writer's book. A book that was only uploaded is always
 * worked on as an illustrator. */
export function currentView(project: Pick<Project, 'id' | 'mode'>): View {
  if (project.mode !== 'writer') return 'illustrator'
  return read(`view:${project.id}`) === 'illustrator' ? 'illustrator' : 'writer'
}
export const saveView = (projectId: string, view: View) => write(`view:${projectId}`, view)

/** Reactive version of `currentView`, for components that must follow the switch. */
export function useView(project: Pick<Project, 'id' | 'mode'>): View {
  return useSyncExternalStore(subscribe, () => currentView(project))
}

/** What the right-hand panel of the book page shows; the top bar buttons set it. */
export function useSide(projectId: string): [Side, (side: Side) => void] {
  const key = `side:${projectId}`
  const value = useSyncExternalStore(subscribe, () => read(key))
  const side: Side = value === 'review' || value === 'versions' ? value : 'chat'
  return [side, (next) => write(key, next)]
}
