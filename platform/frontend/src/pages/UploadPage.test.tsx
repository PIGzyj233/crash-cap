import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { ApiProvider } from '../api/context'
import { createMockApiClient } from '../api/mock'
import { UploadPage } from './UploadPage'

vi.mock('../api/hashImportFile', () => ({ hashImportFile: async () => 'a'.repeat(64) }))
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); sessionStorage.clear() })

it('uploads an unpaired file directly into the current Workspace and fixes the batch label', async () => {
  const api=createMockApiClient()
  const workspace=(await api.listWorkspaces())[0]
  const init=vi.spyOn(api,'initUpload').mockResolvedValue({ uploaded_by: { id: 'usr_test', username: 'tester', display_name: 'Test User' },upload_id:'upl_ui',method:'PUT',url:'https://objects.test/one',headers:{},expires_in:900})
  vi.spyOn(api,'completeUpload').mockResolvedValue({ uploaded_by: { id: 'usr_test', username: 'tester', display_name: 'Test User' },upload_id:'upl_ui',status:'VERIFYING',verification_status:'VERIFYING',version_conflict:false})
  const accepted={ uploaded_by: { id: 'usr_test', username: 'tester', display_name: 'Test User' },upload_id:'upl_ui',status:'ACCEPTED' as const,version_conflict:false,verification_status:'ACCEPTED' as const,workspace_id:workspace.id,availability:'waiting_for_pair' as const,artifact_entry_id:'art_ui'}
  vi.spyOn(api,'waitForUpload').mockResolvedValue(accepted)
  vi.spyOn(api,'getUpload').mockResolvedValue(accepted)
  const {container}=render(<ApiProvider api={api}><MemoryRouter><UploadPage workspace={workspace}/></MemoryRouter></ApiProvider>)
  fireEvent.change(screen.getByLabelText('版本（可选）'),{target:{value:'11.0.1'}})
  fireEvent.change(container.querySelector('input[type=file]')!,{target:{files:[new File(['pdb'],'alone.pdb')]}})
  await screen.findByText('alone.pdb')
  fireEvent.click(screen.getByRole('button',{name:/上传 1 个文件/}))
  await screen.findByText('等待配对')
  expect(init).toHaveBeenCalledWith(expect.objectContaining({workspace_id:workspace.id,version:'11.0.1',file_kind:'pdb'}))
  expect((screen.getByLabelText('版本（可选）') as HTMLInputElement).disabled).toBe(true)
  expect(screen.queryByText(/选择 Build/)).toBeNull()
  fireEvent.click(screen.getByRole('button',{name:'清空列表'}))
  await waitFor(()=>expect((screen.getByLabelText('版本（可选）') as HTMLInputElement).disabled).toBe(false))
})

it.each([
  { scope: 'public', picker: 'files' },
  { scope: 'public', picker: 'directory' },
  { scope: 'workspace', picker: 'files' },
  { scope: 'workspace', picker: 'directory' },
])('queues and uploads DLL/PDB over HTTP in $scope using $picker', async ({ scope, picker }) => {
  // On a non-loopback HTTP origin getRandomValues exists, but randomUUID does not.
  vi.stubGlobal('crypto', { getRandomValues: crypto.getRandomValues.bind(crypto) })
  const api = createMockApiClient()
  const workspace = (await api.listWorkspaces())[0]
  const user = { id: 'usr_test', username: 'tester', display_name: 'Test User' }
  const accepted = (id: string) => ({ uploaded_by: user, upload_id: id, status: 'ACCEPTED' as const,
    verification_status: 'ACCEPTED' as const, version_conflict: false, availability: 'symbols_available' as const })
  const init = vi.spyOn(api, 'initUpload').mockImplementation(async request => ({ uploaded_by: user,
    upload_id: `upl_${request.filename}`, method: 'PUT', url: 'https://objects.test/file', headers: {}, expires_in: 900 }))
  const transfer = vi.spyOn(api, 'uploadPresigned').mockResolvedValue({ parts: [] })
  vi.spyOn(api, 'completeUpload').mockImplementation(async id => accepted(id))
  vi.spyOn(api, 'waitForUpload').mockImplementation(async id => accepted(id))
  vi.spyOn(api, 'getUpload').mockImplementation(async id => accepted(id))
  const { container } = render(<ApiProvider api={api}><MemoryRouter initialEntries={['/upload?intent=symbols&target=public']}>
    <UploadPage workspace={scope === 'workspace' ? workspace : undefined} />
  </MemoryRouter></ApiProvider>)
  const files = [new File(['dll'], 'xrtc_router.dll'), new File(['pdb'], 'xrtc_router.dll.pdb')]
  const input = container.querySelector(picker === 'directory' ? 'input[webkitdirectory]' : 'input[type=file]:not([webkitdirectory])')!
  fireEvent.change(input, { target: { files } })
  await screen.findByText('xrtc_router.dll')
  await screen.findByText('xrtc_router.dll.pdb')
  expect(init).not.toHaveBeenCalled()
  const button = screen.getByRole('button', { name: '上传 2 个文件' })
  expect(button).toHaveProperty('disabled', false)
  fireEvent.click(button)
  await screen.findByText('本次上传 · 2 / 2 已入库')
  expect(init).toHaveBeenCalledTimes(2)
  expect(transfer).toHaveBeenCalledTimes(2)
  for (const filename of ['xrtc_router.dll', 'xrtc_router.dll.pdb']) {
    expect(init).toHaveBeenCalledWith(expect.objectContaining({ filename, workspace_id: scope === 'workspace' ? workspace.id : null }))
  }
  const saved = JSON.parse(sessionStorage.getItem('crashcap.upload-queues.v1:test')!)
  const rows = saved[scope === 'workspace' ? workspace.id : 'public'].rows
  expect(new Set(rows.map((row: { key: string }) => row.key)).size).toBe(2)
})

it('shows a selection error and allows selecting the same file again', async () => {
  vi.stubGlobal('crypto', { getRandomValues: vi.fn().mockImplementation(() => { throw new Error('unavailable') }) })
  const api = createMockApiClient()
  const init = vi.spyOn(api, 'initUpload')
  const { container } = render(<ApiProvider api={api}><MemoryRouter initialEntries={['/upload?intent=symbols&target=public']}>
    <UploadPage />
  </MemoryRouter></ApiProvider>)
  const file = new File(['pdb'], 'retry.pdb')
  const input = container.querySelector('input[webkitdirectory]')!
  fireEvent.change(input, { target: { files: [file] } })
  await screen.findByText('无法将所选文件加入上传列表，请重新选择后重试。')
  expect(init).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: '上传 0 个文件' })).toHaveProperty('disabled', true)
  vi.unstubAllGlobals()
  fireEvent.change(input, { target: { files: [file] } })
  await screen.findByText('retry.pdb')
  expect(screen.queryByText('无法将所选文件加入上传列表，请重新选择后重试。')).toBeNull()
  expect(screen.getByRole('button', { name: '上传 1 个文件' })).toHaveProperty('disabled', false)
})
