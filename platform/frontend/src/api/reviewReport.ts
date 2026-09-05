import { sha256 } from '@noble/hashes/sha2.js'
import type { CanonicalReport } from '../types'

const MAX_REPORT_BYTES = 64 * 1024 * 1024

export async function readReviewReport(response: Response, occurrenceId: string, runId: string) {
  if (!response.body) throw new Error('报告内容为空')
  const reader = response.body.getReader()
  const chunks: Uint8Array[] = []
  let size = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      size += value.byteLength
      if (size > MAX_REPORT_BYTES) {
        await reader.cancel()
        throw new Error('报告超过审核读取上限')
      }
      chunks.push(value)
    }
  } finally {
    reader.releaseLock()
  }
  const bytes = new Uint8Array(size)
  let offset = 0
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength }
  const report = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)) as CanonicalReport
  if (!report || !['2.0'].includes(report.schema_version) || report.analysis_id !== runId || report.occurrence_id !== occurrenceId) {
    throw new Error('报告身份或版本不匹配，请重新选择报告')
  }
  const digest = Array.from(sha256(bytes), (value) => value.toString(16).padStart(2, '0')).join('')
  return { report, sha256: digest }
}
