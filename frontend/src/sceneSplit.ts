import { api } from './api'
import { ask } from './dialogs'
import type { Translate } from './i18n'

/** What a press on "Split into scenes" leads to. */
export type SplitChoice = { show: string } | { split: true; again: boolean } | null

/**
 * A chapter already split is shown, not split again (owner's notes 27.11): its scenes are
 * offered first, and a new split asks once more with the price. null: the user cancelled.
 */
export async function chooseSplit(t: Translate, chapterId: string): Promise<SplitChoice> {
  const estimate = await api.splitEstimate(chapterId)
  if (estimate.existing && estimate.first_scene_id) {
    const show = await ask(t('scenes.split.exists', { n: estimate.existing }), {
      yes: t('scenes.split.show'),
      no: t('scenes.split.again'),
    })
    if (show) return { show: estimate.first_scene_id }
  }
  const question =
    t('scenes.split.confirm', {
      input: estimate.input_tokens.toLocaleString(),
      output: estimate.output_tokens.toLocaleString(),
    }) + (estimate.existing ? t('scenes.split.replace', { n: estimate.existing }) : '')
  const labels = estimate.existing ? { yes: t('scenes.split.again') } : {}
  if (!(await ask(question, labels))) return null
  return { split: true, again: estimate.existing > 0 }
}
