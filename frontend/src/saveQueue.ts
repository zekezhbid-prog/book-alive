// Draft saves run one after another, and actions that read the whole book
// (commit, rollback) wait for them, so a version never misses the last keystrokes.
let tail: Promise<unknown> = Promise.resolve()

export function enqueueSave(save: () => Promise<unknown>): Promise<unknown> {
  tail = tail.then(save, save)
  return tail
}

export function savesSettled(): Promise<unknown> {
  return tail.catch(() => undefined)
}
