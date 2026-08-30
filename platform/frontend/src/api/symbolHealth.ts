import type { SymbolHealthRow } from '../types'

function normalizeIdentifier(value: string | null): string | null {
  const normalized = value?.normalize('NFKC').trim().toLocaleLowerCase('en-US')
  return normalized || null
}

function normalizeFilename(value: string | null): string {
  const normalized = value?.normalize('NFKC').trim().replaceAll('/', '\\') ?? ''
  return normalized.split('\\').at(-1)?.toLocaleLowerCase('en-US') ?? ''
}

/** Mirrors the API's symbol identity contract without exposing its internal hash. */
export function symbolHealthIdentity(row: SymbolHealthRow): string {
  const codeId = normalizeIdentifier(row.code_id)
  const debugId = normalizeIdentifier(row.debug_id)
  if (codeId || debugId) return JSON.stringify({ kind: 'ids', code_id: codeId, debug_id: debugId })
  return JSON.stringify({
    kind: 'files',
    code_file: normalizeFilename(row.code_file),
    debug_file: normalizeFilename(row.debug_file),
  })
}

/**
 * Symbol Health is an inventory view while Missing Symbols is the durable
 * Current-Analysis impact view. Keep inventory rows, overlay exact identities,
 * and append impacts that cannot honestly be assigned to a Build module.
 */
export function mergeSymbolHealthRows(
  inventory: SymbolHealthRow[],
  affected: SymbolHealthRow[],
): SymbolHealthRow[] {
  const affectedByIdentity = new Map<string, SymbolHealthRow>()
  for (const row of affected) {
    const identity = symbolHealthIdentity(row)
    const current = affectedByIdentity.get(identity)
    if (!current) {
      affectedByIdentity.set(identity, row)
      continue
    }
    const occurrenceIds = [...new Set([...current.occurrence_ids, ...row.occurrence_ids])].sort()
    affectedByIdentity.set(identity, {
      ...current,
      affected_occurrence_count: occurrenceIds.length,
      occurrence_ids: occurrenceIds,
      first_seen: current.first_seen < row.first_seen ? current.first_seen : row.first_seen,
      last_seen: current.last_seen > row.last_seen ? current.last_seen : row.last_seen,
    })
  }

  const represented = new Set<string>()
  const merged = inventory.map((row) => {
    const identity = symbolHealthIdentity(row)
    represented.add(identity)
    const impact = affectedByIdentity.get(identity)
    if (!impact) return row
    return {
      ...row,
      affected_occurrence_count: impact.affected_occurrence_count,
      occurrence_ids: impact.occurrence_ids,
      first_seen: impact.first_seen,
      last_seen: impact.last_seen,
    }
  })

  for (const [identity, impact] of affectedByIdentity) {
    if (!represented.has(identity)) merged.push(impact)
  }
  return merged
}
