import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import { ApiProvider } from '../api/context'
import { createMockApiClient } from '../api/mock'
import { UploadPage } from './UploadPage'

vi.mock('../api/hashImportFile', () => ({ hashImportFile: async () => 'a'.repeat(64) }))
afterEach(cleanup)

it('uploads an unpaired file directly into the current Workspace and fixes the batch label', async () => {
  const api=createMockApiClient()
  const workspace=(await api.listWorkspaces())[0]
  const init=vi.spyOn(api,'initUpload').mockResolvedValue({upload_id:'upl_ui',method:'PUT',url:'https://objects.test/one',headers:{},expires_in:900})
  vi.spyOn(api,'completeUpload').mockResolvedValue({upload_id:'upl_ui',status:'VERIFYING',verification_status:'VERIFYING',version_conflict:false})
  const accepted={upload_id:'upl_ui',status:'ACCEPTED' as const,version_conflict:false,verification_status:'ACCEPTED' as const,workspace_id:workspace.id,availability:'waiting_for_pair' as const,artifact_entry_id:'art_ui'}
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
