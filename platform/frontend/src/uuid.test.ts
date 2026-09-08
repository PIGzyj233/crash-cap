import { afterEach, expect, it, vi } from 'vitest'
import { createUuid } from './uuid'

afterEach(() => vi.unstubAllGlobals())

it('generates distinct RFC 4122 version 4 identifiers without secure-context APIs', () => {
  vi.stubGlobal('crypto', { getRandomValues: crypto.getRandomValues.bind(crypto) })
  const ids = Array.from({ length: 100 }, createUuid)
  expect(new Set(ids).size).toBe(ids.length)
  for (const id of ids) expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
})
