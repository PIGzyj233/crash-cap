import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { AnalysisDemandStatus } from './AnalysisDemandStatus'

afterEach(cleanup)

describe('AnalysisDemandStatus', () => {
  it('shows withdrawn basis together with an expired dump without claiming current evidence is valid', () => {
    render(<AnalysisDemandStatus demand={{ state: 'cannot_recompute', not_before: null, withdrawn_basis_pair_ids: ['pair'] }} />)
    expect(screen.getByRole('status').textContent).toContain('符号依据已停用')
    expect(screen.getByRole('status').textContent).toContain('DMP 已不可用')
    expect(screen.getByRole('status').textContent).toContain('不能继续视为有效')
  })
  it('explains coalescing without promising report completion', () => {
    render(<AnalysisDemandStatus demand={{ state: 'coalescing', not_before: '2026-09-04T08:00:00Z' }} />)
    expect(screen.getByRole('status').textContent).toContain('不是报告完成时限')
    expect(screen.getByText(/最早重新检查时间/).textContent).toContain('不是报告完成时间')
  })
  it('distinguishes retaining a report from updating it', () => {
    render(<AnalysisDemandStatus demand={{ state: 'retained', not_before: null }} />)
    expect(screen.getByRole('status').textContent).toContain('未替换当前报告')
    expect(screen.queryByText('报告已更新')).toBeNull()
  })
  it('does not show a stale due date for a terminal result', () => {
    render(<AnalysisDemandStatus demand={{ state: 'updated', not_before: '2026-09-04T08:00:00Z' }} />)
    expect(screen.getByText('报告已更新')).toBeTruthy()
    expect(screen.queryByText(/最早重新检查时间/)).toBeNull()
  })
  it('handles no demand and unknown future states safely', () => {
    const { rerender } = render(<AnalysisDemandStatus demand={null} />)
    expect(screen.queryByRole('status')).toBeNull()
    rerender(<AnalysisDemandStatus demand={{ state: 'future', not_before: 'invalid' }} />)
    expect(screen.getByRole('status').textContent).toContain('分析状态待确认')
    expect(screen.queryByText(/Invalid Date/)).toBeNull()
  })
})
