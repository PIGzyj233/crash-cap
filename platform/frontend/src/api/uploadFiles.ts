import type { CompleteUploadResponse,UploadInput } from '../types';
import { CrashCapApiError,type CrashCapApi } from './client';
import { hashImportFile } from './hashImportFile';

export type UploadState = { state: '待上传' | '上传中' | '校验中' | '已入库' | '失败'; progress: number; uploadId?: string; result?: CompleteUploadResponse; error?: string }
export const supportedUpload = (file: File) => /\.(exe|dll|pdb|dmp)$/i.test(file.name)
export const uploadKind = (file: File): UploadInput['file_kind'] => /\.pdb$/i.test(file.name) ? 'pdb' : /\.dmp$/i.test(file.name) ? 'dmp' : 'pe'
export const availabilityLabels: Record<string, string> = { waiting_for_pair: '等待配对', symbols_available: '符号可用', identity_conflict: '身份冲突', no_debug_identity: '无调试身份', validating: '校验中', storage_unavailable: '存储暂不可用' }

async function retry<T>(action: () => Promise<T>): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    try { return await action() } catch (error) {
      const transient = error instanceof TypeError || (error instanceof CrashCapApiError && (error.status === 0 || error.status >= 500 || error.status === 429))
      if (!transient || attempt >= 2) throw error
      await new Promise(resolve => setTimeout(resolve, 500 * 2 ** attempt))
    }
  }
}

export async function uploadFile(api: CrashCapApi, file: File, workspaceId: string | null, version: string | null, update: (state: Partial<UploadState>) => void) {
  try {
    update({ state: '上传中', progress: 0, error: undefined })
    const sha256 = await hashImportFile(file)
    const init = await retry(() => api.initUpload({ workspace_id: workspaceId, file_kind: uploadKind(file), filename: file.name, size: file.size, sha256, version, source: 'browser' }))
    update({ uploadId: init.upload_id })
    const parts = await retry(() => api.uploadPresigned(init, file, progress => update({ progress })))
    update({ state: '校验中', progress: 100 })
    update({ result: await retry(() => api.completeUpload(init.upload_id, parts)) })
    const result = await api.waitForUpload(init.upload_id, { maxAttempts: 900 })
    update({ result })
    if (result.status !== 'ACCEPTED') throw new Error(result.rejection_reason ?? '文件验收失败')
    update({ state: '已入库' })
    return result
  } catch (error) {
    update({ state: '失败', error: error instanceof Error ? error.message : '上传失败' })
    return undefined
  }
}
