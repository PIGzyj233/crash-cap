import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { components } from '../generated/openapi'
import { ModuleSymbolSelection } from './ModuleSymbolSelection'

vi.mock('./CatalogOrigins', () => ({ CatalogOrigins: ({ pairId }: { pairId: string }) => <button>{pairId}</button> }))
afterEach(cleanup)
const selection: components['schemas']['Canonical11Module']['selection'] = {
  module_index: 0, identity: { code_id: 'abc', debug_id: 'def', architecture: 'x86_64' },
  state: 'conflict', reason: 'identity_conflict', candidates_complete: true,
  candidate_pair_ids: ['pair-a', 'pair-b'], unavailable_pair_ids: ['pair-c'], selected_pair_id: null,
  candidate_evidence: { object_key: 'private-key', sha256: 'a'.repeat(64) }, review_refs: [],
}

it('retains every frozen candidate without choosing a conflict winner', () => {
  render(<ModuleSymbolSelection selection={selection} />)
  fireEvent.click(screen.getByText('身份冲突'))
  for (const id of ['pair-a', 'pair-b', 'pair-c']) expect(screen.getByRole('button', { name: id })).toBeTruthy()
  expect(screen.queryByText('该次选用')).toBeNull()
  expect(screen.getByText('该次不可用')).toBeTruthy()
  expect(screen.queryByText('private-key')).toBeNull()
})

it('does not describe an incomplete single-candidate enumeration as unique', () => {
  render(<ModuleSymbolSelection selection={{ ...selection, state: 'indeterminate', reason: 'enumeration_failed', candidates_complete: false, candidate_pair_ids: ['pair-a'], unavailable_pair_ids: [] }} />)
  fireEvent.click(screen.getByText('尚不能确定'))
  expect(screen.getByText('候选尚未枚举完整，以下列表不能证明匹配唯一。')).toBeTruthy()
  expect(screen.queryByText('唯一配对')).toBeNull()
})

it('shows a loaded Microsoft PDB independently from an absent imported pair', () => {
  render(<ModuleSymbolSelection selection={{ ...selection, state: 'none', reason: 'missing', candidate_pair_ids: [], unavailable_pair_ids: [] }} outcomes={[{
    source_id: 'crash-cap:microsoft', stage: 'download_pdb', outcome: 'found', failure_class: 'none', reason: 'downloaded', diagnostic_ref: { object_key: 'raw', sha256: 'a'.repeat(64) },
  }]} />)
  expect(screen.getByText('PDB 已加载 · Microsoft 官方符号源')).toBeTruthy()
  expect(screen.getByText('未找到配对')).toBeTruthy()
})

it('does not claim PDB loading from a successful PE download', () => {
  render(<ModuleSymbolSelection selection={selection} outcomes={[{
    source_id: 'crash-cap:microsoft', stage: 'download_pe', outcome: 'found', failure_class: 'none', reason: 'downloaded', diagnostic_ref: { object_key: 'raw', sha256: 'a'.repeat(64) },
  }]} />)
  expect(screen.getByText('PDB 未记录请求结果')).toBeTruthy()
  expect(screen.queryByText(/PDB 已加载/)).toBeNull()
})
