import { api } from './api'
import { ask } from './dialogs'
import type { Translate } from './i18n'

/**
 * Ask before the model splits a chapter, with the price. A chapter already split keeps its
 * proposals and is not split again without this (owner's notes 27.11, items 14 and 25);
 * the cards made before stay either way.
 */
export async function confirmSplit(t: Translate, chapterId: string, again: boolean): Promise<boolean> {
  const estimate = await api.splitEstimate(chapterId)
  const question =
    t('scenes.split.confirm', {
      input: estimate.input_tokens.toLocaleString(),
      output: estimate.output_tokens.toLocaleString(),
    }) + (again ? t('scenes.split.replace') : '')
  return ask(question, again ? { yes: t('scenes.split.again') } : {})
}
