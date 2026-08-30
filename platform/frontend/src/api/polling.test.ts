import { describe, expect, it } from 'vitest'
import { getOccurrencePollingInterval, getPollingInterval, isTerminalStatus } from './polling'

describe('Phase 1 polling contract', () => {
  it('polls analysis states every two seconds', () => {
    expect(getPollingInterval('ANALYZING')).toBe(2_000)
    expect(getPollingInterval('MATCHING_SYMBOLS')).toBe(2_000)
    expect(getPollingInterval('GROUPING')).toBe(2_000)
  })

  it('polls queued uploads every ten seconds', () => {
    expect(getPollingInterval('QUEUED')).toBe(10_000)
    expect(getPollingInterval('UPLOADED')).toBe(10_000)
  })

  it('stops on all terminal states and when no run exists', () => {
    expect(getPollingInterval('COMPLETE')).toBe(false)
    expect(getPollingInterval('PARTIAL')).toBe(false)
    expect(getPollingInterval('FAILED')).toBe(false)
    expect(getPollingInterval(undefined)).toBe(false)
    expect(isTerminalStatus('TIMEOUT')).toBe(true)
    expect(isTerminalStatus('ANALYZING')).toBe(false)
  })

  it('keeps polling a new latest attempt even while the usable Current is terminal', () => {
    const current = { id: 'run-current', status: 'PARTIAL' as const }
    expect(getOccurrencePollingInterval(current, { id: 'run-latest', status: 'ANALYZING' })).toBe(2_000)
    expect(getOccurrencePollingInterval(current, { id: 'run-latest', status: 'QUEUED' })).toBe(10_000)
    expect(getOccurrencePollingInterval(current, { id: 'run-latest', status: 'FAILED' })).toBe(false)
    expect(getOccurrencePollingInterval(current, current)).toBe(false)
  })
})
