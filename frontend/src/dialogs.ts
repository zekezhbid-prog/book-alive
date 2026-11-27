/**
 * The site's own replacements for the browser's confirm() and prompt(): the system
 * windows look like an error from Windows, these follow the page's style. Call `ask` or
 * `askText` from anywhere; <DialogHost /> shows them one at a time.
 */

export interface DialogRequest {
  message: string
  /** null: a yes/no question. A string: a text field starting with this value. */
  text: string | null
  /** Own words for the two buttons of a yes/no question instead of "Cancel" and "OK". */
  yes?: string
  no?: string
  resolve: (answer: string | boolean | null) => void
}

let show: ((request: DialogRequest) => void) | null = null

/** Called by the host when it mounts; null when it goes away. */
export function setDialogHost(handler: typeof show) {
  show = handler
}

/** Asks a yes/no question; resolves true on OK (or on `labels.yes`). */
export function ask(message: string, labels: { yes?: string; no?: string } = {}): Promise<boolean> {
  return new Promise((resolve) => {
    if (!show) return resolve(window.confirm(message))
    show({ message, text: null, ...labels, resolve: (answer) => resolve(answer === true) })
  })
}

/** Asks for a line of text; resolves null on cancel. */
export function askText(message: string, initial = ''): Promise<string | null> {
  return new Promise((resolve) => {
    if (!show) return resolve(window.prompt(message, initial))
    show({ message, text: initial, resolve: (answer) => resolve(typeof answer === 'string' ? answer : null) })
  })
}
