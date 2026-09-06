import { cleanup,fireEvent,render,screen,waitFor } from '@testing-library/react'
import { afterEach,expect,it,vi } from 'vitest'
import { MemoryRouter,useLocation } from 'react-router-dom'
import { App } from '../App'
import { ApiProvider } from '../api/context'
import { createMockApiClient } from '../api/mock'
import type { ArtifactEntry,SymbolIssueDetail } from '../types'

vi.mock('../api/hashImportFile', () => ({ hashImportFile: async () => 'a'.repeat(64) }))
afterEach(() => { cleanup(); sessionStorage.clear(); localStorage.clear() })
function Location() { const location = useLocation(); return <output data-testid="location">{location.pathname}{location.search}</output> }
function show(path: string, api = createMockApiClient()) {
  return render(<ApiProvider api={api}><MemoryRouter initialEntries={[path]}><Location /><App /></MemoryRouter></ApiProvider>)
}
const artifact: ArtifactEntry = { id: 'art_public', file_id: 'file_shared', workspace_id: null, name: 'renderer.pdb', version: '1.2', kind: 'pdb', sha256: 'a'.repeat(64), size: 1024, code_id: null, debug_id: 'abc1', availability: 'symbols_available', source: 'browser', created_at: '2026-09-06T00:00:00Z' }

it('shows three primary task areas and an honest first-use overview', async () => {
  const api = createMockApiClient()
  const base = await api.getWorkspaceOverview('wsp_demo')
  vi.spyOn(api, 'getWorkspaceOverview').mockResolvedValue({ ...base, total_occurrences: 0, total_artifact_entries: 2, window_occurrences: 0, average_analysis_duration_ms: null, recent_occurrences: [] })
  show('/w/wsp_demo/overview', api)
  expect(await screen.findByText('开始分析第一份崩溃报告')).toBeTruthy()
  expect(screen.getAllByRole('menuitem')).toHaveLength(3)
  expect(screen.getByRole('link', { name: '上传 DMP 查看报告' }).getAttribute('href')).toContain('intent=dump')
  expect(screen.queryByText('Quality')).toBeNull()
  expect(screen.getByText(/已入库 2 份/)).toBeTruthy()
  expect(screen.getByRole('link', { name: /上传文件/ }).querySelector('button')).toBeNull()
})

it('carries attention and time window from overview into the crash list', async () => {
  show('/w/wsp_demo/overview')
  const attention = await screen.findByRole('link', { name: /最近分析失败/ })
  const href = attention.getAttribute('href')!
  expect(href).toContain('attention=latest_attempt_failed')
  expect(href).toContain('from=')
  fireEvent.click(attention)
  expect(await screen.findByRole('heading', { name: '崩溃记录' })).toBeTruthy()
  expect(screen.getByTestId('location').textContent).toBe(href)
  expect(screen.queryByLabelText('测试批次（人工）')).toBeNull()
})

it('keeps cursor pagination independent of browser history and restores the list after a report', async () => {
  const api = createMockApiClient()
  const base = await api.listOccurrences('wsp_demo')
  const row = base.items.find(row => row.id === 'occ_demo')!
  vi.spyOn(api, 'listOccurrences').mockImplementation(async (_workspace, filters) => ({ items: [row], next_cursor: filters?.cursor ? null : 'page_two' }))
  show('/w/wsp_demo/occurrences?version=1.2', api)
  await screen.findByText('EXCEPTION_ACCESS_VIOLATION')
  fireEvent.click(screen.getByRole('button', { name: /下一页/ }))
  await waitFor(() => expect(screen.getByTestId('location').textContent).toContain('cursor=page_two'))
  const link = screen.getByRole('link', { name: /^EXCEPTION_ACCESS_VIOLATION/ })
  fireEvent.click(link)
  fireEvent.click(await screen.findByRole('link', { name: /返回崩溃记录/ }))
  expect(await screen.findByRole('heading', { name: '崩溃记录' })).toBeTruthy()
  expect(screen.getByTestId('location').textContent).toContain('cursor=page_two')
  fireEvent.click(screen.getByRole('button', { name: /上一页/ }))
  expect(screen.getByTestId('location').textContent).toBe('/w/wsp_demo/occurrences?version=1.2')
})

it('reads consumer-scoped files and opens a shareable file detail', async () => {
  const api = createMockApiClient()
  const browse = vi.spyOn(api, 'browseArtifacts').mockResolvedValue({ items: [artifact], next_cursor: null })
  const detail = vi.spyOn(api, 'getArtifact').mockResolvedValue({ artifact, pairs: [] })
  show('/w/wsp_demo/artifacts?origin=public', api)
  fireEvent.click(await screen.findByRole('link', { name: /renderer.pdb/ }))
  expect(await screen.findByRole('heading', { name: 'renderer.pdb' })).toBeTruthy()
  expect(browse).toHaveBeenCalledWith('wsp_demo', expect.objectContaining({ origin: 'public' }))
  expect(detail).toHaveBeenCalledWith('wsp_demo', 'art_public')
  fireEvent.click(screen.getByRole('link', { name: '返回文件库' }))
  expect(screen.getByTestId('location').textContent).toBe('/w/wsp_demo/artifacts?origin=public')
})

it('keeps file readiness separate from report impact and carries issue context into upload', async () => {
  const api = createMockApiClient()
  const detail: SymbolIssueDetail = { issue: { id: 'issue_one', code_file: 'renderer.dll', debug_file: 'renderer.pdb', code_id: 'code1', debug_id: 'abc1', reasons: { missing_pdb: 1 }, affected_occurrence_count: 1, first_seen: artifact.created_at, last_seen: artifact.created_at }, files: { items: [artifact], next_cursor: null }, availability: 'symbols_available' }
  vi.spyOn(api, 'getSymbolIssue').mockResolvedValue(detail)
  vi.spyOn(api, 'listOccurrences').mockResolvedValue({ items: [], next_cursor: null })
  show('/w/wsp_demo/symbols/issue_one', api)
  expect(await screen.findByText('相关符号文件已可用，当前报告仍需更新')).toBeTruthy()
  expect(screen.queryByText('当前报告中的问题已解决')).toBeNull()
  fireEvent.click(screen.getByRole('link', { name: '补传符号文件' }))
  expect(await screen.findByRole('heading', { name: '上传程序与符号' })).toBeTruthy()
  expect(screen.getByTestId('location').textContent).toContain('issue=issue_one')
  expect((screen.getByRole('link', { name: '返回来源页面' })).getAttribute('href')).toBe('/w/wsp_demo/symbols/issue_one')
  expect(screen.getByText(/影响 1 份报告/)).toBeTruthy()
})

it('preselects the public destination when uploading from the public file library', async () => {
  show('/artifacts')
  fireEvent.click(await screen.findByRole('link', { name: '上传程序与 PDB' }))
  expect(await screen.findByRole('heading', { name: '上传程序与符号' })).toBeTruthy()
  expect(screen.getByText('公共空间（EXE / DLL / PDB）')).toBeTruthy()
  expect(screen.getByRole('link', { name: '返回来源页面' }).getAttribute('href')).toBe('/artifacts')
})

it('continues a pending upload across navigation and restores accepted receipts after remount', async () => {
  const api = createMockApiClient()
  const accepted = { upload_id: 'upl_kept', status: 'ACCEPTED' as const, verification_status: 'ACCEPTED' as const, version_conflict: false, workspace_id: 'wsp_demo', artifact_entry_id: 'art_kept', availability: 'waiting_for_pair' as const }
  vi.spyOn(api, 'initUpload').mockResolvedValue({ upload_id: 'upl_kept', method: 'PUT', url: 'https://objects.test/file', headers: {}, expires_in: 900 })
  vi.spyOn(api, 'completeUpload').mockResolvedValue({ upload_id: 'upl_kept', status: 'VERIFYING', verification_status: 'VERIFYING', version_conflict: false })
  let finish!: (value: typeof accepted) => void
  const waiting = vi.spyOn(api, 'waitForUpload').mockImplementation(() => new Promise(resolve => { finish = resolve }))
  const get = vi.spyOn(api, 'getUpload').mockResolvedValue(accepted)
  const mounted = show('/w/wsp_demo/upload', api)
  await screen.findByRole('heading', { name: '上传文件' })
  fireEvent.change(mounted.container.querySelector('input[type=file]')!, { target: { files: [new File(['symbols'], 'waiting.pdb')] } })
  await screen.findByText('waiting.pdb')
  fireEvent.click(screen.getByRole('button', { name: '上传 1 个文件' }))
  await waitFor(() => expect(waiting).toHaveBeenCalled())
  fireEvent.click(screen.getByRole('link', { name: '返回来源页面' }))
  await screen.findByRole('heading', { name: 'Desktop Client' })
  fireEvent.click(screen.getByRole('link', { name: /上传文件/ }))
  expect(await screen.findByText('waiting.pdb')).toBeTruthy()
  finish(accepted)
  expect(await screen.findByText('等待配对')).toBeTruthy()
  mounted.unmount()
  show('/w/wsp_demo/upload', api)
  expect(await screen.findByRole('link', { name: '查看文件详情' })).toBeTruthy()
  expect(get).toHaveBeenCalledWith('upl_kept')
  expect(sessionStorage.getItem('crashcap.upload-queues.v1')).not.toContain('objects.test')
})

it('maps legacy stack links to diagnosis while preserving the selected historical run', async () => {
  const api = createMockApiClient()
  await api.getOccurrence('occ_demo'); await api.getOccurrence('occ_demo')
  show('/w/wsp_demo/occurrences/occ_demo?tab=stack&run=run_demo', api)
  expect(await screen.findByRole('tab', { name: '诊断' })).toBeTruthy()
  await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('/w/wsp_demo/occurrences/occ_demo?run=run_demo'))
  expect(screen.queryByText('分析历史与报告选择依据')).toBeNull()
  fireEvent.click(screen.getByRole('tab', { name: '历史与复核' }))
  expect(await screen.findByText('分析历史与报告选择依据')).toBeTruthy()
})

it('recovers an uncertain receipt without requiring or reuploading the local file', async () => {
  sessionStorage.setItem('crashcap.upload-queues.v1', JSON.stringify({ wsp_demo: { target: 'wsp_demo', version: '2.4', busy: true, rows: [{ key: 'kept', name: 'already-sent.pdb', relativePath: 'already-sent.pdb', size: 1024, state: '校验中', progress: 100, uploadId: 'upl_uncertain' }] } }))
  const api = createMockApiClient()
  vi.spyOn(api, 'getUpload').mockRejectedValueOnce(new TypeError('temporarily offline')).mockResolvedValue({ upload_id: 'upl_uncertain', status: 'ACCEPTED', verification_status: 'ACCEPTED', version_conflict: false, workspace_id: 'wsp_demo', artifact_entry_id: 'art_recovered', availability: 'waiting_for_pair' })
  const initialize = vi.spyOn(api, 'initUpload')
  show('/w/wsp_demo/upload', api)
  expect(await screen.findByText('状态待恢复')).toBeTruthy()
  fireEvent.click(screen.getByRole('button', { name: '恢复验收状态' }))
  expect(await screen.findByRole('link', { name: '查看文件详情' })).toHaveProperty('pathname', '/w/wsp_demo/artifacts/art_recovered')
  expect(initialize).not.toHaveBeenCalled()
})

it('restores the list scroll position after navigating through a report', async () => {
  let position = 0
  const scroll = vi.spyOn(window, 'scrollTo').mockImplementation((...args: unknown[]) => {
    position = typeof args[0] === 'number' ? Number(args[1]) : (args[0] as ScrollToOptions).top ?? 0
  })
  const y = vi.spyOn(window, 'scrollY', 'get').mockImplementation(() => position)
  const height = vi.spyOn(document.documentElement, 'scrollHeight', 'get').mockReturnValue(3000)
  try {
    const api = createMockApiClient()
    await api.getOccurrence('occ_demo'); await api.getOccurrence('occ_demo')
    show('/w/wsp_demo/occurrences', api)
    const report = (await screen.findAllByRole('link', { name: /^EXCEPTION_ACCESS_VIOLATION/ })).find(link => link.getAttribute('href')?.endsWith('/occ_demo'))!
    await waitFor(() => expect(scroll).toHaveBeenCalled())
    position = 720
    fireEvent.scroll(window)
    fireEvent.click(report)
    await screen.findByRole('heading', { name: /EXCEPTION_ACCESS_VIOLATION/ })
    await waitFor(() => expect(position).toBe(0))
    fireEvent.click(screen.getByRole('link', { name: /返回崩溃记录/ }))
    await screen.findByRole('heading', { name: '崩溃记录' })
    await waitFor(() => expect(position).toBe(720))
  } finally {
    cleanup(); scroll.mockRestore(); y.mockRestore(); height.mockRestore()
  }
})
