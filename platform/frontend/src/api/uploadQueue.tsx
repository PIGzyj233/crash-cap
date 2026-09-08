import { captureAccount, currentUser } from './authTransport'
import { createContext,useContext,useEffect,useRef,useState,type ReactNode } from 'react'
import type { CrashCapApi } from './client'
import { supportedUpload,uploadFile,type UploadState } from './uploadFiles'

export type QueueRow = Omit<UploadState, 'state'> & {
  key: string; name: string; size: number; relativePath: string; file?: File
  state: UploadState['state'] | '需重新选择' | '状态待恢复'
}
export type UploadBatch = { target?: string; version: string; rows: QueueRow[]; busy: boolean }
const STORAGE_KEY = 'crashcap.upload-queues.v1'
const emptyBatch = (key: string): UploadBatch => ({ target: key === 'platform' ? undefined : key, version: '', rows: [], busy: false })

function restore(storageKey: string): Record<string, UploadBatch> {
  try {
    const saved = JSON.parse(sessionStorage.getItem(storageKey) ?? '{}') as Record<string, UploadBatch>
    return Object.fromEntries(Object.entries(saved).filter(([, batch]) => Array.isArray(batch.rows) && typeof batch.version === 'string').map(([key, batch]) => [key, { ...batch, busy: false, rows: batch.rows.map(row => ({ ...row, file: undefined, state: row.state === '已入库' ? '已入库' : row.uploadId ? '校验中' : '需重新选择', error: row.uploadId ? undefined : '请重新选择此文件以继续上传' })) }]))
  } catch { return {} }
}

type QueueContextValue = {
  batches: Record<string, UploadBatch>
  patch: (key: string, patch: Partial<UploadBatch>) => void
  addFiles: (key: string, files: File[]) => void
  start: (key: string, failedOnly?: boolean) => Promise<void>
  recover: (key: string) => Promise<void>
}
const QueueContext = createContext<QueueContextValue | null>(null)

export function UploadQueueProvider({ api, onChanged, children }: { api: CrashCapApi; onChanged: () => void; children: ReactNode }) {
  const storageKey = useRef(`${STORAGE_KEY}:${currentUser()?.id ?? "test"}`).current
  const checkAccount = useRef(captureAccount()).current
  const isOwner = () => { try { checkAccount(); return true } catch { return false } }
  const [batches, setBatches] = useState(() => restore(storageKey))
  const current = useRef(batches)
  const recovered = useRef(false)
  const update = (key: string, change: (batch: UploadBatch) => UploadBatch) => {
    const next = { ...current.current, [key]: change(current.current[key] ?? emptyBatch(key)) }
    current.current = next; setBatches(next)
    try {
      sessionStorage.setItem(storageKey, JSON.stringify(Object.fromEntries(Object.entries(next).map(([scope, batch]) => [scope, { ...batch, rows: batch.rows.map(({ file: _file, ...row }) => row) }]))))
    } catch { /* Uploads still work if storage is disabled or full. */ }
  }
  const rowUpdate = (scope: string, id: string, patch: Partial<QueueRow>) => update(scope, batch => ({ ...batch, rows: batch.rows.map(row => row.key === id ? { ...row, ...patch } : row) }))
  const recover = async (scope: string) => {
    if (!isOwner()) return
    const rows = current.current[scope]?.rows.filter(row => row.uploadId) ?? []
    await Promise.all(rows.map(async row => {
      if (row.state !== '已入库') rowUpdate(scope, row.key, { state: '校验中', error: undefined })
      try {
        let result = await api.getUpload(row.uploadId!)
        if (result.status === 'UPLOADED' || result.status === 'VERIFYING') result = await api.waitForUpload(row.uploadId!, { maxAttempts: 900 })
        if (result.status === 'ACCEPTED') rowUpdate(scope, row.key, { result, state: '已入库', error: undefined })
        else if (result.status === 'REJECTED') rowUpdate(scope, row.key, { result, state: '失败', error: result.rejection_reason ?? '文件被拒收，请重新选择正确文件' })
        else rowUpdate(scope, row.key, { result, state: '需重新选择', error: '文件尚未完成传输，请重新选择以继续' })
      } catch {
        rowUpdate(scope, row.key, { state: row.state === '已入库' ? '已入库' : '状态待恢复', error: '暂时无法读取验收状态，上传 ID 已保留，请点击恢复验收状态重试' })
      }
    }))
    onChanged()
  }
  useEffect(() => {
    if (recovered.current) return
    recovered.current = true
    Object.keys(current.current).forEach(scope => { void recover(scope) })
  }, [api]) // The provider survives route changes; recovery runs once per page load.

  const start = async (key: string, failedOnly = false) => {
    const batch = current.current[key]
    if (!batch?.target || batch.busy || batch.target === 'public' && batch.rows.some(row => /\.dmp$/i.test(row.name))) return
    update(key, value => ({ ...value, busy: true }))
    try {
      for (const row of batch.rows.filter(row => row.state !== '已入库' && row.state !== '状态待恢复' && row.state !== '校验中' && (!failedOnly || row.state === '失败' || row.state === '需重新选择'))) {
        if (!isOwner()) break
        if (!row.file) { rowUpdate(key, row.key, { state: '需重新选择', error: '请重新选择此文件以继续上传' }); continue }
        await uploadFile(api, row.file, batch.target === 'public' ? null : batch.target, batch.version.trim() || null, patch => rowUpdate(key, row.key, patch))
      }
      if (!isOwner()) return
      for (const row of current.current[key].rows.filter(row => row.state === '已入库' && row.uploadId)) {
        if (!isOwner()) break
        try { rowUpdate(key, row.key, { result: await api.getUpload(row.uploadId!) }) } catch { /* Acceptance remains valid. */ }
      }
      onChanged()
    } finally { update(key, value => ({ ...value, busy: false })) }
  }
  return <QueueContext.Provider value={{ batches, start, recover, patch: (key, patch) => update(key, batch => ({ ...batch, ...patch })), addFiles: (key, files) => update(key, batch => {
    const rows = [...batch.rows]
    for (const file of files.filter(supportedUpload)) {
      const replaceIndex = rows.findIndex(row => !row.file && row.state !== '已入库' && row.state !== '校验中' && row.state !== '状态待恢复' && row.name === file.name && row.size === file.size)
      if (replaceIndex >= 0) rows[replaceIndex] = { ...rows[replaceIndex], file, state: '待上传', error: undefined }
      else rows.push({ key: crypto.randomUUID(), name: file.name, size: file.size, relativePath: file.webkitRelativePath || file.name, file, state: '待上传', progress: 0 })
    }
    return { ...batch, rows }
  }) }}>{children}</QueueContext.Provider>
}

export function useUploadBatch(key: string) {
  const queue = useContext(QueueContext)
  if (!queue) throw new Error('UploadQueueProvider is required')
  return { batch: queue.batches[key] ?? emptyBatch(key), patch: (patch: Partial<UploadBatch>) => queue.patch(key, patch), addFiles: (files: File[]) => queue.addFiles(key, files), start: (failedOnly = false) => queue.start(key, failedOnly), recover: () => queue.recover(key) }
}
