import { File as NodeFile } from 'node:buffer'
import { createHash } from 'node:crypto'
import { expect, it } from 'vitest'
import { hashImportFile } from './hashImportFile'

it('matches SHA-256 across chunk boundaries', async () => {
  const bytes = new Uint8Array(2 * 1_048_576 + 17).fill(123)
  const file = new NodeFile([bytes], 'large.pdb') as unknown as File
  expect(await hashImportFile(file)).toBe(createHash('sha256').update(bytes).digest('hex'))
})
