import type { MessageKey } from './i18n'

/** The name the import gives the author's private chapter (backend `importing/private.py`). */
const PRIVATE_TITLE = 'Личные данные автора'

/** A chapter's title as shown: the private chapter's stock name in the interface language
 * (owner's notes 28.11, item 56), anything else as the book has it. */
export function shownTitle(title: string, t: (key: MessageKey) => string): string {
  if (title === PRIVATE_TITLE) return t('chapter.private.title')
  return title || t('book.untitled')
}
