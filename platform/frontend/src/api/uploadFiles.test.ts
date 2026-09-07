import { clearIdentity, setIdentity } from './authTransport'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { createApiClient } from './client'
import { uploadFile, type UploadState } from './uploadFiles'

vi.mock('./hashImportFile', () => ({ hashImportFile: async () => 'a'.repeat(64) }))

afterEach(() => clearIdentity())

describe('single file upload acceptance', () => {
  it('uses one v3 path and accepts a retained PDB waiting for a later PE', async () => {
    const api = createApiClient()
    const init = vi.spyOn(api, 'initUpload').mockResolvedValue({ uploaded_by: { id: 'usr_test', username: 'tester', display_name: 'Test User' }, upload_id:'upl_one', method:'PUT', url:'https://objects.test/signed', headers:{}, expires_in:900 })
    vi.spyOn(api, 'uploadPresigned').mockResolvedValue({parts:[]})
    vi.spyOn(api, 'completeUpload').mockResolvedValue({ uploaded_by: { id: 'usr_test', username: 'tester', display_name: 'Test User' },upload_id:'upl_one',status:'VERIFYING',verification_status:'VERIFYING',version_conflict:false})
    vi.spyOn(api, 'waitForUpload').mockResolvedValue({ uploaded_by: { id: 'usr_test', username: 'tester', display_name: 'Test User' },upload_id:'upl_one',status:'ACCEPTED',version_conflict:false,verification_status:'ACCEPTED',availability:'waiting_for_pair'})
    const states: Partial<UploadState>[] = []
    const result = await uploadFile(api,new File(['pdb'],'renamed.pdb'),'wsp_exact',null,state=>states.push(state))
    expect(init).toHaveBeenCalledWith({workspace_id:'wsp_exact',file_kind:'pdb',filename:'renamed.pdb',size:3,sha256:'a'.repeat(64),version:null,source:'browser'})
    expect(result?.status).toBe('ACCEPTED')
    expect(states.map(s=>s.state).filter(Boolean)).toEqual(['上传中','校验中','已入库'])
  })

  it('keeps rejected file evidence available to a batch that continues', async () => {
    const api=createApiClient()
    vi.spyOn(api,'initUpload').mockResolvedValue({ uploaded_by: { id: 'usr_test', username: 'tester', display_name: 'Test User' },upload_id:'upl_bad',method:'PUT',url:'https://objects.test/signed',headers:{},expires_in:900})
    vi.spyOn(api,'uploadPresigned').mockResolvedValue({parts:[]})
    vi.spyOn(api,'completeUpload').mockResolvedValue({ uploaded_by: { id: 'usr_test', username: 'tester', display_name: 'Test User' },upload_id:'upl_bad',status:'VERIFYING',verification_status:'VERIFYING',version_conflict:false})
    vi.spyOn(api,'waitForUpload').mockResolvedValue({ uploaded_by: { id: 'usr_test', username: 'tester', display_name: 'Test User' },upload_id:'upl_bad',status:'REJECTED',verification_status:'REJECTED',version_conflict:false,rejection_reason:'file_identity_invalid'})
    const state:Partial<UploadState>={}
    expect(await uploadFile(api,new File(['broken'],'broken.dll'),null,'sdk-v1',patch=>Object.assign(state,patch))).toBeUndefined()
    expect(state).toMatchObject({state:'失败',uploadId:'upl_bad',error:'file_identity_invalid',result:{status:'REJECTED'}})
    expect(JSON.stringify(state)).not.toContain('signed')
  })
})


it('stops completion when the account changes during object transfer', async () => {
  const user = { id: 'alice', username: 'alice', display_name: 'Alice', kind: 'human', role: 'member', enabled: true, must_change_password: false }
  setIdentity({ user, csrf_token: 'alice-proof' })
  const api = createApiClient()
  vi.spyOn(api, 'initUpload').mockResolvedValue({ uploaded_by: user, upload_id: 'upl_alice', method: 'PUT', url: 'https://objects.test/signed', headers: {}, expires_in: 900 })
  vi.spyOn(api, 'uploadPresigned').mockImplementation(async () => {
    setIdentity({ user: { ...user, id: 'bob' }, csrf_token: 'bob-proof' })
    return { parts: [] }
  })
  const complete = vi.spyOn(api, 'completeUpload')
  const state: Partial<UploadState> = {}
  await uploadFile(api, new File(['pdb'], 'test.pdb'), 'workspace', null, patch => Object.assign(state, patch))
  expect(complete).not.toHaveBeenCalled()
  expect(state.state).toBe('失败')
  expect(state.error).toContain('账号已切换')
  expect(state.uploadId).toBe('upl_alice')
})
