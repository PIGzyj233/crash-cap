import { afterEach, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { App as AntApp } from 'antd'
import { ApiProvider } from '../api/context'
import { createMockApiClient } from '../api/mock'
import * as discovery from '../api/discoverSymbolPairs'
import * as hashing from '../api/hashImportFile'
import type { SymbolImportResult } from '../types'
import { SymbolImportPage } from './SymbolImportPage'

afterEach(() => { cleanup(); vi.restoreAllMocks() })

it('keeps import disabled when the server capability is off', async () => {
  const api = createMockApiClient()
  const create = vi.spyOn(api, 'createSymbolImport')
  render(<AntApp><ApiProvider api={api}><MemoryRouter><SymbolImportPage /></MemoryRouter></ApiProvider></AntApp>)
  expect(await screen.findByText('独立符号导入尚未启用')).toBeTruthy()
  expect(screen.getByLabelText('选择多个符号文件').hasAttribute('disabled')).toBe(true)
  expect(create).not.toHaveBeenCalled()
})

it('reuses the batch key after an uncertain create and retries one failed upload independently', async () => {
  const api = createMockApiClient()
  vi.spyOn(api, 'getCapabilities').mockResolvedValue({ reader_versions: ['1.0', '1.1'], enabled_writes: ['symbol_imports'], pause_reason: null })
  const pes = [new File(['pe1'], 'first.dll'), new File(['pe2'], 'second.dll')]
  const pdbs = [new File(['pdb1'], 'first.pdb'), new File(['pdb2'], 'second.pdb')]
  vi.spyOn(discovery, 'discoverSymbolPairs').mockResolvedValue({ pairs: pes.map((pe, index) => ({ pe, candidates: [pdbs[index]], pdbName: pdbs[index].name, error: null })), ignored: [] })
  vi.spyOn(hashing, 'hashImportFile').mockResolvedValue('a'.repeat(64))
  const batch: SymbolImportResult = { import_id: 'import-test', items: [1, 2].map((number) => ({ item_id: `item-${number}`, client_pair_id: `pair-${number}`, state: 'staging', pair_id: null, error_code: null, pe_upload_id: `pe-${number}`, pdb_upload_id: `pdb-${number}` })) }
  const create = vi.spyOn(api, 'createSymbolImport').mockRejectedValueOnce(new Error('创建响应丢失')).mockImplementation(async () => structuredClone(batch))
  vi.spyOn(api, 'getSymbolImport').mockImplementation(async () => structuredClone(batch))
  const upload = vi.spyOn(api, 'uploadSymbolImportFile').mockRejectedValueOnce(new Error('单项网络错误')).mockResolvedValue({ upload_id: 'uploaded', state: 'uploaded' })
  vi.spyOn(api, 'completeSymbolImportItem').mockImplementation(async (_, itemId) => {
    batch.items.find((item) => item.item_id === itemId)!.state = 'available'
    return structuredClone(batch)
  })
  render(<AntApp><ApiProvider api={api}><MemoryRouter><SymbolImportPage /></MemoryRouter></ApiProvider></AntApp>)
  const input = screen.getByLabelText('选择多个符号文件')
  await waitFor(() => expect(input.hasAttribute('disabled')).toBe(false))
  fireEvent.change(screen.getByLabelText('来源说明'), { target: { value: 'QA folder' } })
  fireEvent.change(input, { target: { files: [...pes, ...pdbs] } })
  const submit = await screen.findByRole('button', { name: '提交 2 对文件' })
  fireEvent.click(submit)
  expect(await screen.findByText('创建响应丢失')).toBeTruthy()
  fireEvent.click(submit)
  expect(await screen.findByText('单项网络错误')).toBeTruthy()
  expect(await screen.findByText('已生效')).toBeTruthy()
  expect(create.mock.calls[0][0]).toEqual(create.mock.calls[1][0])
  await waitFor(() => expect(screen.getByRole('button', { name: '重试上传' }).hasAttribute('disabled')).toBe(false))
  fireEvent.click(screen.getByRole('button', { name: '重试上传' }))
  await waitFor(() => expect(screen.getAllByText('已生效')).toHaveLength(2))
  expect(upload.mock.calls.filter((call) => call[1] === 'item-2')).toHaveLength(2)
})
