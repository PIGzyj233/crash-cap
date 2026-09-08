import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'
import { ApiProvider } from './context'
import { createApiClient } from './client'
import { clearIdentity, setIdentity, type LoginIdentity } from './authTransport'
import { useUploadBatch } from './uploadQueue'

vi.mock('./hashImportFile', () => ({ hashImportFile: async () => 'a'.repeat(64) }))
const alice: LoginIdentity = { user: { id: 'alice', username: 'alice', display_name: 'Alice', role: 'member', kind: 'human', enabled: true, must_change_password: false }, csrf_token: 'test-proof' }
afterEach(() => { cleanup(); clearIdentity(); sessionStorage.clear() })

it('does not let an old transfer overwrite receipts after the same user signs in again', async () => {
  setIdentity(alice)
  const api = createApiClient()
  vi.spyOn(api, 'initUpload').mockResolvedValue({ uploaded_by: alice.user, upload_id: 'upl_old', method: 'PUT', url: 'https://objects.test/old', headers: {}, expires_in: 900 })
  let completeTransfer!: (value: { parts: [] }) => void
  let progress!: (percent: number) => void
  const transfer = new Promise<{ parts: [] }>(resolve => { completeTransfer = resolve })
  const upload = vi.spyOn(api, 'uploadPresigned').mockImplementation((_upload, _file, onProgress) => { progress = onProgress!; return transfer })
  const complete = vi.spyOn(api, 'completeUpload')
  const get = vi.spyOn(api, 'getUpload').mockResolvedValue({ uploaded_by: alice.user, upload_id: 'upl_old', status: 'UPLOADING', verification_status: 'UPLOADING', version_conflict: false })
  const wrapper = ({ children }: { children: ReactNode }) => <ApiProvider api={api}>{children}</ApiProvider>
  const original = renderHook(() => useUploadBatch('workspace'), { wrapper })
  act(() => { original.result.current.patch({ target: 'workspace', version: 'old' }); original.result.current.addFiles([new File(['pdb'], 'test.pdb')]) })
  let started!: Promise<void>
  act(() => { started = original.result.current.start() })
  await waitFor(() => expect(upload).toHaveBeenCalledOnce())
  act(() => clearIdentity())
  original.unmount()
  setIdentity(alice)
  const fresh = renderHook(() => useUploadBatch('workspace'), { wrapper })
  await waitFor(() => expect(get).toHaveBeenCalledOnce())
  await waitFor(() => expect(fresh.result.current.batch.rows[0].state).toBe('需重新选择'))
  act(() => fresh.result.current.patch({ version: 'new-login' }))
  const saved = sessionStorage.getItem('crashcap.upload-queues.v1:alice')
  await act(async () => { progress(100); completeTransfer({ parts: [] }); await started })
  expect(complete).not.toHaveBeenCalled()
  expect(fresh.result.current.batch.version).toBe('new-login')
  expect(sessionStorage.getItem('crashcap.upload-queues.v1:alice')).toBe(saved)
})

it('stops a multipart upload before starting another part after logout', async () => {
  setIdentity(alice)
  let finish!: (value: Response) => void
  const response = new Promise<Response>(resolve => { finish = resolve })
  const fetcher = vi.fn().mockReturnValue(response)
  const api = createApiClient({ fetcher })
  const upload = api.uploadPresigned({ uploaded_by: alice.user, upload_id: 'upl_parts', method: 'PUT', url: 'https://objects.test/file', headers: {}, expires_in: 900,
    multipart: { upload_id: 'multipart', part_size: 2, parts: [{ part_number: 1, url: 'https://objects.test/one' }, { part_number: 2, url: 'https://objects.test/two' }] } }, new File(['four'], 'test.pdb'))
  const rejected = expect(upload).rejects.toThrow('账号已切换或退出')
  clearIdentity()
  finish(new Response(null, { status: 200, headers: { ETag: 'part-one' } }))
  await rejected
  expect(fetcher).toHaveBeenCalledTimes(1)
})
