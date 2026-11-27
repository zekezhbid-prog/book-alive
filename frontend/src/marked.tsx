import type { ReactNode } from 'react'

/** The text with the fragments the model added lit, in the order they stand. */
export function marked(text: string, added: string[]): ReactNode[] {
  const parts: ReactNode[] = []
  let rest = text
  for (;;) {
    const hits = added
      .map((fragment) => ({ fragment, at: rest.indexOf(fragment) }))
      .filter((hit) => hit.fragment && hit.at >= 0)
      .sort((a, b) => a.at - b.at)
    if (!hits.length) break
    const { fragment, at } = hits[0]
    parts.push(rest.slice(0, at), <mark key={parts.length}>{fragment}</mark>)
    rest = rest.slice(at + fragment.length)
  }
  parts.push(rest)
  return parts
}
