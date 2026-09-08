import { QueryClient,QueryClientProvider } from '@tanstack/react-query'
import { cleanup,fireEvent,render,screen,waitFor } from '@testing-library/react'
import { afterEach,expect,it,vi } from 'vitest'
import { PublicSymbolFill } from './PublicSymbolFill'

const { get,create } = vi.hoisted(() => ({ get: vi.fn(), create: vi.fn() }))
vi.mock('../api/context', () => ({ useApi: () => ({ getPublicSymbolJob: get, createPublicSymbolJob: create }) }))
afterEach(() => { cleanup(); vi.resetAllMocks() })

it('retries a lost response with the same request and only refreshes the public job', async () => {
  get.mockResolvedValue(null)
  create.mockRejectedValueOnce(new Error('响应未确认')).mockResolvedValueOnce({ id: 'job' })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(['occurrence', 'o'], { current_run_id: 'original' })
  render(<QueryClientProvider client={client}><PublicSymbolFill workspaceId="w" occurrenceId="o" /></QueryClientProvider>)
  const button = await screen.findByRole('button', { name: '补齐 Windows 公共符号' })
  await waitFor(() => expect(button.hasAttribute('disabled')).toBe(false))
  fireEvent.click(button)
  await screen.findByText('响应未确认')
  fireEvent.click(button)
  await waitFor(() => expect(create).toHaveBeenCalledTimes(2))
  expect(create.mock.calls[1]).toEqual(create.mock.calls[0])
  expect(client.getQueryData(['occurrence', 'o'])).toEqual({ current_run_id: 'original' })
  client.clear()
})

it('shows validated, unavailable and skipped identities separately', async () => {
  get.mockResolvedValue({ id: 'job', status: 'completed', items: [
    { status: 'downloaded', debug_file: 'kernel32.pdb', debug_id: 'a'.repeat(33) },
    { status: 'not_found', debug_file: 'unknown.pdb' },
    { status: 'skipped', code_file: 'avcodec-61.dll', reason: 'debug_identity_unavailable' },
  ] })
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<QueryClientProvider client={client}><PublicSymbolFill workspaceId="w" occurrenceId="o" /></QueryClientProvider>)
  await screen.findByText(/已补齐 1 · 未找到 1 · 失败 0 · 跳过 1/)
  fireEvent.click(screen.getByText('查看公共符号处理结果'))
  expect(await screen.findByText('缺少有效的 PDB 文件名或 GUID/Age')).toBeTruthy()
  expect(create).not.toHaveBeenCalled()
  client.clear()
})
