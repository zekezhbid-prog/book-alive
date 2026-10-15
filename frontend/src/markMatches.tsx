import type { ReactNode } from 'react'

const escapeRegExp = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/**
 * Wraps every case-insensitive occurrence of `query` in <mark>; the text between them goes
 * through `rest`, so names inside a chapter still become links.
 */
export function markMatches(
  text: string,
  query: string | undefined,
  rest: (text: string, key: string) => ReactNode[],
): ReactNode[] {
  const needle = query?.trim()
  if (!needle || needle.length < 2) return rest(text, 'm')
  // A capturing group keeps the matches in the split result, at odd positions.
  return text.split(new RegExp(`(${escapeRegExp(needle)})`, 'giu')).flatMap((part, i): ReactNode[] =>
    i % 2 ? [<mark key={`m${i}`}>{part}</mark>] : rest(part, `m${i}`),
  )
}
