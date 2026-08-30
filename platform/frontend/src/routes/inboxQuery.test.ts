import { describe, expect, it } from 'vitest'
import { parseInboxQuery, serializeInboxQuery } from './inboxQuery'

describe('Inbox query string contract', () => {
  it('normalizes valid filters and removes invalid or unknown values', () => {
    const parsed = parseInboxQuery(new URLSearchParams('q=%20render%20&crash_type=crash&latest_status=FAILED&grouping=bad&from=not-a-date&unknown=1'))
    expect(parsed.filters).toEqual({ q: 'render', crash_type: 'crash', latest_status: 'FAILED' })
    expect(parsed.canonical.toString()).toBe('crash_type=crash&latest_status=FAILED&q=render')
    expect(parsed.changed).toBe(true)
  })

  it('drops inverted ranges and preserves an opaque cursor for browser history', () => {
    const parsed = parseInboxQuery(new URLSearchParams('from=2026-08-02T00%3A00%3A00Z&to=2026-08-01T00%3A00%3A00Z&cursor=opaque-v1'))
    expect(parsed.filters).toEqual({ cursor: 'opaque-v1' })
    expect(serializeInboxQuery({ latest_status: 'FAILED', cursor: 'next' }).toString()).toBe('latest_status=FAILED&cursor=next')
  })

  it('removes overlong search text rather than sending a 422 loop', () => {
    const parsed = parseInboxQuery(new URLSearchParams({ q: 'x'.repeat(129) }))
    expect(parsed.filters.q).toBeUndefined()
    expect(parsed.canonical.toString()).toBe('')
  })
})
