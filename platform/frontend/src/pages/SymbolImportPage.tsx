import { useRef, useState } from 'react'
import { Alert, Button, Card, Input, Select, Space, Tag, Typography } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { useApi } from '../api/context'
import { useCapabilities, usePageVisible } from '../api/hooks'
import { discoverSymbolPairs, type DiscoveredPair } from '../api/discoverSymbolPairs'
import { hashImportFile } from '../api/hashImportFile'
import { DataTable } from '../components/DataTable'
import { CatalogOrigins } from '../components/CatalogOrigins'
import { PageTitle } from '../components/ui'
import { routePaths } from '../routes/routePaths'
import type { SymbolImportRequest, SymbolImportResult } from '../types'

type Selection = DiscoveredPair & { key: string; selected: File | null }
const labels: Record<string, string> = { staging: '等待上传', queued: '等待验证', verifying: '正在验证', available: '已生效', rejected: '验证未通过', retry_exhausted: '验证重试已用尽' }
const importErrors: Record<string, string> = {
  ARTIFACT_IDENTIFY_FAILED: '无法识别 PE/PDB 格式，请检查文件是否完整且未损坏。',
  ARTIFACT_TOO_LARGE: '文件超过服务端允许的大小。',
  UNSUPPORTED_ARTIFACT_KIND: '文件类型或生成格式不受支持。',
  CATALOG_PAIR_INVALID: 'PE 与 PDB 未通过完整配对验证，请核对是否来自同一次构建。',
  IMPORT_STAGING_CHANGED: '暂存文件与上传校验不一致，请重新提交原始文件。',
}

export function SymbolImportPage() {
  const api = useApi()
  const queryClient = useQueryClient()
  const capabilities = useCapabilities()
  const enabled = capabilities.data?.enabled_writes.includes('symbol_imports') === true
  const visible = usePageVisible()
  const [params, setParams] = useSearchParams()
  const importId = params.get('import')
  const [rows, setRows] = useState<Selection[]>([])
  const [source, setSource] = useState('')
  const [busy, setBusy] = useState(false)
  const [activity, setActivity] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [itemErrors, setItemErrors] = useState<Record<string, string>>({})
  const [ignored, setIgnored] = useState(0)
  const [selectionNotice, setSelectionNotice] = useState<string | null>(null)
  const request = useRef<SymbolImportRequest | null>(null)
  const result = useQuery({
    queryKey: ['symbol-import', importId],
    queryFn: () => api.getSymbolImport(importId!),
    enabled: Boolean(importId), retry: false,
    refetchInterval: (query) => visible && !query.state.error && query.state.data?.items.some((item) => ['queued', 'verifying'].includes(item.state)) ? 2_000 : false,
  })
  const locked = busy || Boolean(importId) || Boolean(request.current)
  const eligible = rows.filter((row) => row.selected && row.selected.size > 0 && !row.error)
  const selectFiles = async (files: File[]) => {
    setBusy(true); setError(null); setActivity('正在发现配对…')
    try {
      const discovered = await discoverSymbolPairs(files)
      setRows(discovered.pairs.map((pair, index) => ({ ...pair, key: `pair-${index + 1}`, selected: pair.candidates.length === 1 && pair.candidates[0].size > 0 ? pair.candidates[0] : null })))
      setIgnored(discovered.ignored.length)
      const used = new Set(discovered.pairs.flatMap((pair) => pair.candidates))
      const unmatched = files.filter((file) => /\.pdb$/i.test(file.name) && !used.has(file)).length
      setSelectionNotice(!discovered.pairs.length ? '未找到 PE 文件，请同时选择 EXE/DLL 等产品文件及其完整 PDB。' : unmatched ? `${unmatched} 个 PDB 未列入候选配对，请检查是否同时选择了引用它们的 PE。` : null)
    } catch (cause) { setError(cause instanceof Error ? cause.message : '文件读取失败') }
    finally { setBusy(false); setActivity('') }
  }
  const transfer = async (batch: SymbolImportResult, onlyItem?: string) => {
    for (const item of batch.items) {
      if (item.state !== 'staging' || (onlyItem && item.item_id !== onlyItem)) continue
      const row = rows.find((candidate) => candidate.key === item.client_pair_id)
      if (!row?.selected) continue
      setItemErrors((errors) => { const next = { ...errors }; delete next[item.item_id]; return next })
      try {
        setActivity(`上传 ${row.pe.name}`)
        await api.uploadSymbolImportFile(batch.import_id, item.item_id, 'pe', row.pe)
        setActivity(`上传 ${row.selected.name}`)
        await api.uploadSymbolImportFile(batch.import_id, item.item_id, 'pdb', row.selected)
        await api.completeSymbolImportItem(batch.import_id, item.item_id)
      } catch (cause) {
        setItemErrors((errors) => ({ ...errors, [item.item_id]: cause instanceof Error ? cause.message : '上传失败' }))
      }
    }
    queryClient.setQueryData(['symbol-import', batch.import_id], await api.getSymbolImport(batch.import_id))
  }
  const submit = async () => {
    if (!enabled || busy || eligible.length === 0 || eligible.length > 200 || !source.trim()) return
    setBusy(true); setError(null)
    try {
      if (!request.current) {
        const pairs: SymbolImportRequest['pairs'] = []
        for (const row of eligible) {
          setActivity(`校验文件：${row.pe.name}`)
          const claim = async (file: File) => ({ name: file.name, raw_size: file.size, raw_sha256: await hashImportFile(file) })
          pairs.push({ client_pair_id: row.key, pe: await claim(row.pe), pdb: await claim(row.selected!) })
        }
        request.current = { idempotency_key: crypto.randomUUID(), source_label: source.trim(), pairs }
      }
      const batch = await api.createSymbolImport(request.current)
      queryClient.setQueryData(['symbol-import', batch.import_id], batch)
      setParams({ import: batch.import_id }, { replace: true })
      await transfer(batch)
    } catch (cause) { setError(cause instanceof Error ? cause.message : '导入失败') }
    finally { setBusy(false); setActivity('') }
  }
  const retry = async (itemId: string) => {
    if (!enabled || busy || !importId) return
    setBusy(true); setError(null)
    try { await transfer(await api.getSymbolImport(importId), itemId) }
    catch (cause) { setError(cause instanceof Error ? cause.message : '重试失败') }
    finally { setBusy(false); setActivity('') }
  }
  const reset = () => { request.current = null; setRows([]); setItemErrors({}); setError(null); setIgnored(0); setSelectionNotice(null); setParams({}) }

  return <div className="platform-page">
    <Link to={routePaths.home}>返回平台主页</Link>
    <PageTitle title="导入符号" description="选择产品 PE 和完整 PDB 文件。无需 Git、源码或 Build；验证通过的配对供各 Workspace 按精确身份使用。" />
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      {!enabled && <Alert type="info" showIcon message={capabilities.isError ? '无法读取导入能力，请重试' : '独立符号导入尚未启用'} action={capabilities.isError ? <Button onClick={() => void capabilities.refetch()}>重试</Button> : undefined} />}
      {error && <Alert type="error" showIcon message={error} />}
      <Card title="选择文件">
        <Space direction="vertical" size={12} style={{ width: '100%' }}>
          <label>来源说明<Input maxLength={512} value={source} disabled={locked} onChange={(event) => setSource(event.target.value)} placeholder="例如：QA 提供的 9 月 4 日产品目录" /></label>
          <label>选择多个文件<input aria-label="选择多个符号文件" type="file" multiple disabled={locked || !enabled} accept=".exe,.dll,.sys,.ocx,.pdb" onChange={(event) => { void selectFiles(Array.from(event.target.files ?? [])); event.target.value = '' }} /></label>
          <label>选择目录<input aria-label="选择符号目录" type="file" multiple {...{ webkitdirectory: '' }} disabled={locked || !enabled} onChange={(event) => { void selectFiles(Array.from(event.target.files ?? [])); event.target.value = '' }} /></label>
          <Typography.Text type="secondary">压缩包请先在本地解压。候选发现不代表验证通过；同名文件有歧义时需选择配对。</Typography.Text>
          {ignored > 0 && <Typography.Text>已略过 {ignored} 个非 PE/PDB 文件。</Typography.Text>}
          {selectionNotice && <Alert type="warning" showIcon message={selectionNotice} />}
          {rows.length > 0 && <DataTable rowKey="key" dataSource={rows} minWidth={650} columns={[
            { title: 'PE 文件', render: (_, row: Selection) => row.pe.webkitRelativePath || row.pe.name },
            { title: 'PDB 配对', render: (_, row: Selection) => row.error ? <Typography.Text type="danger">{row.error}</Typography.Text> : row.candidates.length === 0 ? <Typography.Text type="warning">缺少 {row.pdbName}，请选择包含该 PDB 的文件集合</Typography.Text> : <Select aria-label={`为 ${row.pe.name} 选择 PDB`} style={{ minWidth: 220 }} disabled={locked} placeholder="选择 PDB 候选" value={row.selected ? row.candidates.indexOf(row.selected) : undefined} options={row.candidates.map((file, index) => ({ value: index, label: (file.webkitRelativePath || file.name) + (file.size === 0 ? '（空文件，不可提交）' : ''), disabled: file.size === 0 }))} onChange={(index) => setRows((current) => current.map((candidate) => candidate.key === row.key ? { ...candidate, selected: row.candidates[index] } : candidate))} /> },
          ]} />}
          {eligible.length > 200 && <Alert type="warning" message="每批最多 200 对，请分批选择文件。" />}
          <Space><Button type="primary" loading={busy} disabled={!enabled || Boolean(importId) || !source.trim() || eligible.length === 0 || eligible.length > 200} onClick={() => void submit()}>提交 {eligible.length} 对文件</Button><Button disabled={busy} onClick={reset}>开始新批次</Button></Space>
          <div role="status" aria-live="polite">{activity}</div>
        </Space>
      </Card>
      {importId && <Card title="逐对结果" extra={<Button disabled={busy} onClick={() => void result.refetch()}>刷新</Button>}>
        <Typography.Paragraph>批次：{importId}</Typography.Paragraph>
        {result.isError && <Alert type="error" message="读取批次失败，请刷新重试。" />}
        <DataTable rowKey="item_id" loading={result.isLoading} dataSource={result.data?.items ?? []} minWidth={650} columns={[
          { title: '配对', render: (_, item) => { const pe = rows.find((row) => row.key === item.client_pair_id)?.pe; return pe ? pe.webkitRelativePath || pe.name : item.client_pair_id } },
          { title: '状态', render: (_, item) => <Tag color={item.state === 'available' ? 'green' : item.state === 'rejected' || item.state === 'retry_exhausted' ? 'red' : 'blue'}>{labels[item.state]}</Tag> },
          { title: '来源', render: (_, item) => item.pair_id ? <CatalogOrigins pairId={item.pair_id} /> : '配对尚未生效' },
          { title: '说明', render: (_, item) => itemErrors[item.item_id] ?? (item.error_code ? `${importErrors[item.error_code] ?? '处理未完成，请保留错误码供排查。'} (${item.error_code})` : item.state === 'available' ? '配对已生效；受影响报告由自动分析流程处理。' : '等待处理') },
          { title: '操作', render: (_, item) => item.state === 'staging' ? <Button disabled={!enabled || busy || !rows.some((row) => row.key === item.client_pair_id && row.selected)} onClick={() => void retry(item.item_id)}>重试上传</Button> : ['rejected', 'retry_exhausted'].includes(item.state) ? <Typography.Text>检查文件后开始新批次重新提交</Typography.Text> : null },
        ]} />
        {!rows.length && <Typography.Text type="secondary">本页只读取已有批次。上传需要本地文件；如文件尚未上传，请开始新批次重新选择。</Typography.Text>}
      </Card>}
    </Space>
  </div>
}
