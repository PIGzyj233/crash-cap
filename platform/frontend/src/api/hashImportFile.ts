import { sha256 } from '@noble/hashes/sha2.js'

export async function hashImportFile(file: File): Promise<string> {
  const hash = sha256.create()
  try {
    for (let offset = 0; offset < file.size; offset += 1_048_576) {
      hash.update(new Uint8Array(await file.slice(offset, offset + 1_048_576).arrayBuffer()))
    }
    return Array.from(hash.digest(), (value) => value.toString(16).padStart(2, '0')).join('')
  } finally {
    hash.destroy()
  }
}
