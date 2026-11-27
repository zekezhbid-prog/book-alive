import type { Angle, ImageInfo, Variant } from '../api'

// A base set is drawn face first: that picture becomes the reference for the rest.
const FULL_ORDER: Angle[] = [
  'face_front',
  'face_three_quarter',
  'face_profile',
  'full_front',
  'full_side',
  'full_back',
]
// A thing-like look (a seed, a stone) needs only two views (owner's notes 25.11).
const OBJECT_ORDER: Angle[] = ['face_front', 'full_front']
// An animal or a bird is drawn whole, a few views without face portraits (owner's notes 26.11).
const CREATURE_ORDER: Angle[] = ['full_front', 'full_three_quarter', 'full_side', 'full_back']

/** The views of a character's look, in the order they are drawn. */
export const orderOf = (shape: Variant['shape'] | undefined): Angle[] =>
  shape === 'object' ? OBJECT_ORDER : shape === 'creature' ? CREATURE_ORDER : FULL_ORDER

/** The newest base picture of a view. */
export function latest(bases: ImageInfo[], view: string) {
  return bases
    .filter((b) => b.angle === view)
    .reduce<ImageInfo | null>((best, b) => (!best || b.created_at > best.created_at ? b : best), null)
}

/** The picture whole, centred on a canvas of the given width/height ratio; the margins are
 * the same picture blurred, so nothing in the picture itself changes. */
export async function padTo(file: File, ratio: number): Promise<File> {
  const bitmap = await createImageBitmap(file)
  const { width, height } = bitmap
  const w = Math.max(width, Math.round(height * ratio))
  const h = Math.max(height, Math.round(width / ratio))
  if (w === width && h === height) return file
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d')!
  const cover = Math.max(w / width, h / height)
  ctx.filter = 'blur(24px) brightness(0.7)'
  ctx.drawImage(bitmap, (w - width * cover) / 2, (h - height * cover) / 2, width * cover, height * cover)
  ctx.filter = 'none'
  ctx.drawImage(bitmap, (w - width) / 2, (h - height) / 2)
  const blob = await new Promise<Blob | null>((done) => canvas.toBlob(done, 'image/png'))
  return blob ? new File([blob], file.name.replace(/\.\w+$/, '') + '.png', { type: 'image/png' }) : file
}
