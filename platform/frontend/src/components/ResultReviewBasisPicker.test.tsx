import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { ResultReviewBasisPicker, reviewPairChanges } from './ResultReviewBasisPicker'
import type { CanonicalReport } from '../types'

const api = vi.hoisted(() => ({ getCatalogOrigins: vi.fn(), getCatalogReviews: vi.fn(), getCatalogReviewEvidence: vi.fn() }))
vi.mock('../api/context', () => ({ useApi: () => api }))
afterEach(() => { cleanup(); vi.resetAllMocks() })

it('requires verified evidence before citing the latest matching provider record', async () => {
  const onChange = vi.fn()
  api.getCatalogOrigins.mockResolvedValue({ qualification_version: 2, state: 'withdrawn' })
  api.getCatalogReviews.mockResolvedValue({ items: [{ id: 'review', qualification_version: 2, state: 'withdrawn', evidence_sha256: 'a'.repeat(64), reason: '配对停用' }] })
  api.getCatalogReviewEvidence.mockRejectedValueOnce(new Error('校验失败')).mockResolvedValueOnce({ reviewer: '提供方', evidence: '已核实不适用' })
  render(<ResultReviewBasisPicker options={[{ pairId: 'pair', label: 'engine.dll', state: 'withdrawn' }]} value={[]} onChange={onChange} disabled={false} />)
  expect(api.getCatalogReviews).not.toHaveBeenCalled()
  fireEvent.click(screen.getByText('查看当前提供方依据'))
  await screen.findByText('校验失败')
  expect(screen.queryByRole('checkbox')).toBeNull()
  expect(onChange).not.toHaveBeenCalled()
  fireEvent.click(screen.getByText('查看当前提供方依据'))
  await screen.findByText('已核实不适用')
  fireEvent.click(screen.getByRole('checkbox'))
  expect(onChange).toHaveBeenCalledWith([{ review_id: 'review', evidence_sha256: 'a'.repeat(64) }])
})

it('rejects an obsolete review when current qualification has changed', async () => {
  api.getCatalogOrigins.mockResolvedValue({ qualification_version: 3, state: 'active' })
  api.getCatalogReviews.mockResolvedValue({ items: [{ id: 'old', qualification_version: 2, state: 'withdrawn' }] })
  render(<ResultReviewBasisPicker options={[{ pairId: 'pair', label: 'engine.dll', state: 'withdrawn' }]} value={[]} onChange={vi.fn()} disabled={false} />)
  fireEvent.click(screen.getByText('查看当前提供方依据'))
  await screen.findByText('当前没有支持此报告变化的有效提供方复核。')
  expect(api.getCatalogReviewEvidence).not.toHaveBeenCalled()
  expect(screen.queryByRole('checkbox')).toBeNull()
})

it('offers only selected pairs that differ between reports, deduplicating repeated modules', () => {
  const report = (ids: string[]) => ({ schema_version: '1.1', modules: ids.map((id) => ({ code_file: `${id}.dll`, selection: { selected_pair_id: id, candidate_pair_ids: ['unselected'] } })) }) as CanonicalReport
  expect(reviewPairChanges(report(['old', 'same', 'old']), report(['same', 'new']))).toEqual([
    { pairId: 'old', label: 'old.dll · 审核前使用', state: 'withdrawn' },
    { pairId: 'new', label: 'new.dll · 候选使用', state: 'active' },
  ])
})
