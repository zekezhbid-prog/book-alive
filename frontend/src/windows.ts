/** Pages opened over the book like windows (style, settings, usage, about). Only one is
 * open at a time: opening another replaces it in the history, so ✕ goes back to the book
 * instead of uncovering the window underneath. */
export function isWindowPage(pathname: string): boolean {
  return /^\/(settings|about)\/?$/.test(pathname) || /^\/projects\/[^/]+\/(style|usage)\/?$/.test(pathname)
}
