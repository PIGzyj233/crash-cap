import { File as NodeFile } from 'node:buffer'
import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import { discoverSymbolPairs, pdbNameFromPe } from './discoverSymbolPairs'

function file(bytes: Uint8Array, name: string, path = ''): File {
  const result = new NodeFile([bytes], name)
  Object.defineProperty(result, 'webkitRelativePath', { value: path })
  return result as unknown as File
}

function peBytes(): Uint8Array {
  const bytes = new Uint8Array(1024)
  const view = new DataView(bytes.buffer)
  view.setUint16(0, 0x5a4d, true)
  view.setUint32(60, 128, true)
  view.setUint32(128, 0x4550, true)
  view.setUint16(132, 0x8664, true)
  view.setUint16(134, 1, true)
  view.setUint16(148, 240, true)
  view.setUint16(152, 0x20b, true)
  view.setUint32(260, 16, true)
  view.setUint32(312, 0x1000, true)
  view.setUint32(316, 28, true)
  view.setUint32(404, 0x1000, true)
  view.setUint32(408, 512, true)
  view.setUint32(412, 512, true)
  const name = new TextEncoder().encode('C:\\build\\different.pdb\0')
  view.setUint32(524, 2, true)
  view.setUint32(528, 24 + name.length, true)
  view.setUint32(536, 600, true)
  view.setUint32(600, 0x53445352, true)
  bytes.set(name, 624)
  return bytes
}

describe('PE/PDB browser discovery', () => {
  it('uses the embedded PDB reference instead of the PE basename', async () => {
    const pe = file(peBytes(), 'engine.dll', 'release/engine.dll')
    const pdb = file(new Uint8Array([1]), 'different.pdb', 'release/different.pdb')
    const wrong = file(new Uint8Array([1]), 'engine.pdb')
    const result = await discoverSymbolPairs([pe, pdb, wrong])
    expect(result.pairs[0]).toMatchObject({ pdbName: 'different.pdb', candidates: [pdb], error: null })
  })

  it('preserves ambiguous candidates and isolates bad files from valid groups', async () => {
    const pe = file(peBytes(), 'engine.dll')
    const first = file(new Uint8Array([1]), 'different.pdb', 'a/different.pdb')
    const second = file(new Uint8Array([2]), 'different.pdb', 'b/different.pdb')
    const bad = file(new Uint8Array([0]), 'broken.dll')
    const result = await discoverSymbolPairs([bad, pe, first, second])
    expect(result.pairs[0].error).toBeTruthy()
    expect(result.pairs[1].candidates).toEqual([first, second])
  })

  it('rejects out-of-file directory pointers without reading arbitrary offsets', async () => {
    const bytes = peBytes()
    new DataView(bytes.buffer).setUint32(536, 0xfffffff0, true)
    await expect(pdbNameFromPe(file(bytes, 'bad.exe'))).rejects.toThrow('读取边界')
  })

  const golden = resolve('../../fixtures/.build/golden/golden_target_release.exe')
  it.skipIf(!existsSync(golden))('reads the actual compiled golden PE', async () => {
    const name = await pdbNameFromPe(file(readFileSync(golden), 'golden_target_release.exe'))
    expect(name.toLowerCase()).toBe('golden_target_release.pdb')
  })
})
