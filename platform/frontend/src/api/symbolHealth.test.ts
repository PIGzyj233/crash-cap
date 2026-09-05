import { describe, expect, it } from 'vitest'
import type { SymbolHealthRow } from '../types'
import { mergeSymbolHealthRows, symbolHealthIdentity } from './symbolHealth'

const base: SymbolHealthRow = {


  code_file: 'target.exe',
  debug_file: 'target.pdb',
  code_id: null,
  debug_id: 'DEBUG-ID',
  status: 'missing',
  affected_occurrence_count: 0,
  first_seen: '2026-08-30T00:00:00Z',
  last_seen: '2026-08-30T00:00:00Z',
  occurrence_ids: [],
}

describe('mergeSymbolHealthRows', () => {
  it('overlays an exact affected identity onto every matching inventory row', () => {
    const affected = { ...base, affected_occurrence_count: 1, occurrence_ids: ['occ_1'] }
    const rows = mergeSymbolHealthRows([base, { ...base, }], [affected])

    expect(rows).toHaveLength(2)
    expect(rows.map((row) => row.occurrence_ids)).toEqual([['occ_1'], ['occ_1']])
  })

  it('keeps a canonical impact separate when a PDB-only Build lacks its code id', () => {
    const affected: SymbolHealthRow = {
      ...base,


      code_file: 'C:\\fixtures\\golden_target.exe',
      debug_file: 'C:\\fixtures\\golden_target.pdb',
      code_id: 'CODE-ID',
      affected_occurrence_count: 1,
      occurrence_ids: ['occ_missing_pe'],
    }
    const rows = mergeSymbolHealthRows([base], [affected])

    expect(symbolHealthIdentity(base)).not.toBe(symbolHealthIdentity(affected))
    expect(rows).toHaveLength(2)
    expect(rows[0].affected_occurrence_count).toBe(0)
    expect(rows[1]).toMatchObject({ occurrence_ids: ['occ_missing_pe'] })
  })
})
