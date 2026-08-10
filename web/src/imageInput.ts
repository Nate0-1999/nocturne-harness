import type {
  ImageAttachmentView,
  ImageMediaType,
  PromptImage,
} from './protocol'

export const MAX_IMAGE_BYTES = 5 * 1024 * 1024
export const IMAGE_ACCEPT = 'image/png,image/jpeg,image/webp,image/gif'

const IMAGE_MEDIA_TYPES: readonly ImageMediaType[] = [
  'image/png',
  'image/jpeg',
  'image/webp',
  'image/gif',
]

export interface PendingImage {
  input: PromptImage
  view: ImageAttachmentView
  local_filename: string
  data_url: string
}

export class ImageInputError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ImageInputError'
  }
}

export function isImageMediaType(value: string): value is ImageMediaType {
  return (IMAGE_MEDIA_TYPES as readonly string[]).includes(value)
}

export function formatImageBytes(value: number): string {
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(value < 10 * 1024 ? 1 : 0)} KiB`
  return `${(value / (1024 * 1024)).toFixed(1)} MiB`
}

export async function prepareImage(file: File): Promise<PendingImage> {
  if (!isImageMediaType(file.type)) {
    throw new ImageInputError('Choose a PNG, JPEG, WebP, or GIF image.')
  }
  if (file.size === 0) {
    throw new ImageInputError('Choose a non-empty image.')
  }
  if (file.size > MAX_IMAGE_BYTES) {
    throw new ImageInputError('Choose an image no larger than 5 MiB.')
  }

  const bytes = new Uint8Array(await file.arrayBuffer())
  if (!signatureMatches(file.type, bytes)) {
    throw new ImageInputError(
      'This file does not match its image type. Export it as PNG, JPEG, WebP, or GIF and try again.',
    )
  }
  const dataBase64 = bytesToBase64(bytes)
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes)
  const sha256 = bytesToHex(new Uint8Array(digest))
  const mediaType = file.type

  return {
    input: {
      kind: 'image',
      media_type: mediaType,
      data_base64: dataBase64,
    },
    view: {
      kind: 'image',
      media_type: mediaType,
      byte_count: bytes.byteLength,
      sha256,
    },
    local_filename: file.name || 'pasted image',
    data_url: `data:${mediaType};base64,${dataBase64}`,
  }
}

function signatureMatches(mediaType: ImageMediaType, bytes: Uint8Array): boolean {
  if (mediaType === 'image/png') {
    return startsWith(bytes, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])
  }
  if (mediaType === 'image/jpeg') {
    return startsWith(bytes, [0xff, 0xd8, 0xff])
  }
  if (mediaType === 'image/gif') {
    return ascii(bytes, 0, 6) === 'GIF87a' || ascii(bytes, 0, 6) === 'GIF89a'
  }
  return ascii(bytes, 0, 4) === 'RIFF' && ascii(bytes, 8, 4) === 'WEBP'
}

function startsWith(bytes: Uint8Array, signature: readonly number[]): boolean {
  return signature.every((value, index) => bytes[index] === value)
}

function ascii(bytes: Uint8Array, start: number, length: number): string {
  if (bytes.byteLength < start + length) return ''
  return String.fromCharCode(...bytes.slice(start, start + length))
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = ''
  const chunkSize = 0x8000
  for (let offset = 0; offset < bytes.byteLength; offset += chunkSize) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize))
  }
  return globalThis.btoa(binary)
}

function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('')
}
