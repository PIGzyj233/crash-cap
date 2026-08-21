import { useEffect, useState } from 'react'
import { Alert, App as AntApp, Button, Card, Col, Descriptions, Form, Input, List, Modal, Row, Select, Space, Spin, Table, Tag, Tooltip, Typography, Upload } from 'antd'
import { CheckCircleOutlined, DownloadOutlined, FileAddOutlined, FileTextOutlined, PlusOutlined, ReloadOutlined, UploadOutlined } from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import { useApi } from '../api/context'
import { useBuild, useBuilds, useCreateBuild, usePutManifest } from '../api/hooks'
import type { Build, BuildManifestInput, UploadKind, VerificationStatus, Workspace } from '../types'
import { HashValue, PageTitle, StatusTag, UploadHint } from '../components/ui'

const { Text } = Typography

function CreateBuildModal({ workspace, open, onClose, onCreated }: { workspace: Workspace; open: boolean; onClose: () => void; onCreated: (buildId: string) => void }) {
  const [form] = Form.useForm<{ version: string; build_number?: string; commit_sha?: string; channel?: string; toolchain?: string }>()
  const createBuild = useCreateBuild(workspace.id)
  const { message } = AntApp.useApp()
  const submit = async () => {
    try {
      const build = await createBuild.mutateAsync(await form.validateFields())
      form.resetFields()
      onClose()
      onCreated(build.id)
      message.success('Build 已创建')
    } catch (error) {
      if (error instanceof Error) message.error(error.message)
    }
  }
  return <Modal title="创建 Build" open={open} okText="创建" cancelText="取消" confirmLoading={createBuild.isPending} onOk={submit} onCancel={onClose}>
    <Form form={form} layout="vertical">
      <Form.Item name="version" label="Version" rules={[{ required: true, message: '请输入 Version' }]}><Input placeholder="2026.08.21.1" /></Form.Item>
      <Row gutter={12}><Col span={12}><Form.Item name="build_number" label="Build number"><Input placeholder="240821-1" /></Form.Item></Col><Col span={12}><Form.Item name="channel" label="Channel"><Input placeholder="stable" /></Form.Item></Col></Row>
      <Form.Item name="commit_sha" label="Commit SHA"><Input placeholder="a1c9f04f…" /></Form.Item>
      <Form.Item name="toolchain" label="Toolchain"><Input placeholder="msvc-19.40" /></Form.Item>
    </Form>
  </Modal>
}

function ManifestCard({ build, workspaceId }: { build: Build; workspaceId: string }) {
  const api = useApi()
  const putManifest = usePutManifest(build.id, workspaceId)
  const { message } = AntApp.useApp()
  const [manifestFile, setManifestFile] = useState<File | null>(null)
  const [rawError, setRawError] = useState<string | null>(null)

  const uploadManifest = async () => {
    if (!manifestFile) return message.warning('请选择 build-manifest.json')
    try {
      const payload = JSON.parse(await manifestFile.text()) as BuildManifestInput
      if (!['1.0', '2.0'].includes(payload.schema_version)) throw new Error('Manifest 必须使用 schema_version=1.0 或 2.0')
      if (!payload.modules?.some((module) => module.role === 'entrypoint')) throw new Error('Manifest 至少需要一个 entrypoint')
      setRawError(null)
      await putManifest.mutateAsync(payload)
      setManifestFile(null)
      message.success('Manifest 已校验并保存')
    } catch (error) {
      const detail = error instanceof SyntaxError ? 'Manifest 不是有效 JSON' : error instanceof Error ? error.message : 'Manifest 保存失败'
      setRawError(detail)
      message.error(detail)
    }
  }

  return <Card title={<span><FileTextOutlined /> Manifest</span>} extra={build.manifest_object_key ? <Tag color="green">已保存</Tag> : <Tag>未上传</Tag>}>
    <Space direction="vertical" style={{ width: '100%' }} size={12}>
      <Upload accept=".json" maxCount={1} beforeUpload={(file) => { setManifestFile(file); setRawError(null); return false }} onRemove={() => setManifestFile(null)} showUploadList={Boolean(manifestFile)}><Button icon={<UploadOutlined />}>选择 build-manifest.json</Button></Upload>
      <UploadHint>v1 用于 PE/PDB；需要源码上下文时使用 v2 的 source_bundle 描述。二进制均走预签名直传。</UploadHint>
      {rawError && <Alert type="error" showIcon message={rawError} />}
      <Button type="primary" icon={<CheckCircleOutlined />} loading={putManifest.isPending} disabled={!manifestFile} onClick={uploadManifest}>校验并保存</Button>
    </Space>
  </Card>
}

function ArtifactCard({ build, workspaceId }: { build: Build; workspaceId: string }) {
  const api = useApi()
  const { message } = AntApp.useApp()
  const queryClient = useQueryClient()
  const [kind, setKind] = useState<UploadKind>('pe')
  const [file, setFile] = useState<File | null>(null)
  const [progress, setProgress] = useState(0)
  const [busy, setBusy] = useState(false)

  const upload = async () => {
    if (!file) return message.warning('请选择文件')
    try {
      setBusy(true)
      const init = await api.initArtifactUpload(build.id, { file_kind: kind, filename: file.name, size: file.size })
      const completion = await api.uploadPresigned(init, file, setProgress)
      await api.completeUpload(init.upload_id, completion)
      const verified = await api.waitForUpload(init.upload_id)
      const verificationStatus = (verified.status ?? verified.verification_status).toUpperCase()
      if (verificationStatus !== 'ACCEPTED') throw new Error(`Artifact 校验未通过：${verificationStatus}`)
      await queryClient.invalidateQueries({ queryKey: ['build', build.id] })
      setFile(null)
      setProgress(100)
      message.success(`${file.name} 已上传并通过校验`)
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'Artifact 上传失败')
    } finally {
      setBusy(false)
    }
  }

  const accept = kind === 'pe' ? '.exe,.dll' : kind === 'pdb' ? '.pdb' : '.zip'
  return <Card title={<span><FileAddOutlined /> Artifact 上传</span>} extra={<Tag color="blue">PE / PDB / SOURCE</Tag>}>
    <Space direction="vertical" style={{ width: '100%' }} size={12}>
      <Row gutter={12}><Col span={8}><Select value={kind} onChange={setKind} style={{ width: '100%' }} options={[{ value: 'pe', label: 'PE / EXE / DLL' }, { value: 'pdb', label: 'PDB' }, { value: 'source_bundle', label: 'Source bundle ZIP' }]} /></Col><Col span={16}><Upload accept={accept} maxCount={1} beforeUpload={(candidate) => { setFile(candidate); setProgress(0); return false }} onRemove={() => setFile(null)} showUploadList={Boolean(file)}><Button icon={<UploadOutlined />}>选择文件</Button></Upload></Col></Row>
      <Alert type="info" showIcon message="Source bundle 安全边界" description="仅 Manifest v2 声明的 ZIP 可上传；ingest 会拒绝路径穿越、符号链接、嵌套压缩包、超限文件与压缩炸弹。" />
      {progress > 0 && <div className="upload-progress-line"><Text type="secondary">直传进度</Text><Text strong>{progress}%</Text></div>}
      <Button type="primary" loading={busy} disabled={!file} onClick={upload}>开始直传</Button>
    </Space>
  </Card>
}

export function BuildPage({ workspace, initialBuildId, onOpenOccurrence }: { workspace: Workspace; initialBuildId?: string; onOpenOccurrence: (occurrenceId: string) => void }) {
  const api = useApi()
  const { message } = AntApp.useApp()
  const { data: builds, isLoading: buildsLoading } = useBuilds(workspace.id)
  const [selectedBuildId, setSelectedBuildId] = useState(initialBuildId)
  const [createOpen, setCreateOpen] = useState(false)
  const [downloadArtifactId, setDownloadArtifactId] = useState<string | null>(null)
  const selectedId = selectedBuildId ?? builds?.[0]?.id
  const { data: build, isLoading: buildLoading } = useBuild(selectedId)

  const downloadArtifact = async (artifactId: string) => {
    try {
      setDownloadArtifactId(artifactId)
      const result = await api.getArtifactDownload(artifactId)
      window.open(result.url, '_blank', 'noopener,noreferrer')
    } catch (error) {
      message.error(error instanceof Error ? error.message : 'Artifact 下载被拒绝')
    } finally {
      setDownloadArtifactId(null)
    }
  }

  useEffect(() => {
    if (!selectedBuildId && builds?.[0]) setSelectedBuildId(builds[0].id)
  }, [builds, selectedBuildId])

  return <div>
    <PageTitle kicker={`${workspace.display_name} / BUILDS`} title="Build 与符号" description="Build 是精确编译产物集合；Version 仅用于展示与聚合，不作为符号匹配键。" extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => setCreateOpen(true)}>创建 Build</Button>} />
    <Row gutter={[18, 18]}>
      <Col xs={24} lg={8}>
        <Card title="Build 列表" className="section-card" bodyStyle={{ padding: 0 }}>
          {buildsLoading ? <div className="center-state"><Spin /></div> : <List dataSource={builds ?? []} locale={{ emptyText: '还没有 Build' }} renderItem={(item) => <List.Item className={item.id === selectedId ? 'build-list-item selected' : 'build-list-item'} onClick={() => setSelectedBuildId(item.id)}><List.Item.Meta title={item.version} description={<span>{item.build_number ?? '无 build number'}<br />{item.commit_sha ? `${item.commit_sha.slice(0, 10)}…` : '无 commit'}</span>} /><span><Tag>{item.modules.length} modules</Tag></span></List.Item>} />}
        </Card>
      </Col>
      <Col xs={24} lg={16}>
        {buildLoading || !build ? <Card><div className="center-state"><Spin /></div></Card> : <Space direction="vertical" size={18} style={{ width: '100%' }}>
          <Card title={<span>{build.version} <Tag color="geekblue">{build.id}</Tag></span>} extra={<Button icon={<ReloadOutlined />} onClick={() => window.location.reload()}>刷新</Button>}>
            <Descriptions size="small" column={{ xs: 1, sm: 2, md: 3 }}>
              <Descriptions.Item label="Build number">{build.build_number ?? '—'}</Descriptions.Item><Descriptions.Item label="Channel">{build.channel ?? '—'}</Descriptions.Item><Descriptions.Item label="Architecture">{build.architecture}</Descriptions.Item><Descriptions.Item label="Toolchain">{build.toolchain ?? '—'}</Descriptions.Item><Descriptions.Item label="Commit"><HashValue value={build.commit_sha} length={14} /></Descriptions.Item><Descriptions.Item label="CI producer">{build.producer ? <Tag color={build.producer === 'msvc' ? 'green' : 'orange'}>{build.producer} · {build.producer_build_id}</Tag> : '手工'}</Descriptions.Item><Descriptions.Item label="Manifest">{build.manifest_schema_version ? <Tag color="blue">v{build.manifest_schema_version}</Tag> : '—'}</Descriptions.Item><Descriptions.Item label="Source bundle">{build.source_bundle_config ? <Tag color="purple">{build.source_bundle_config.archive}</Tag> : <Tag>未声明</Tag>}</Descriptions.Item>
            </Descriptions>
          </Card>
          <ManifestCard build={build} workspaceId={workspace.id} />
          <ArtifactCard build={build} workspaceId={workspace.id} />
          <Card title="Manifest modules" extra={<Text type="secondary">至少一个 entrypoint</Text>}>
            <Table rowKey="id" size="small" pagination={false} dataSource={build.modules} columns={[{ title: 'Module', dataIndex: 'code_file', render: (value: string, row) => <span><Text strong>{value}</Text><br /><Text type="secondary">{row.debug_file ?? '无 PDB'}</Text></span> }, { title: 'Role', dataIndex: 'role', render: (value: string) => <Tag color={value === 'entrypoint' ? 'purple' : value === 'owned' ? 'blue' : 'default'}>{value}</Tag> }, { title: 'PE/PDB', key: 'artifacts', render: (_, row) => <span>{row.artifact_count ?? 0}</span> }, { title: '状态', key: 'status', render: (_, row) => row.missing_occurrence_count ? <Tag color="orange">{row.missing_occurrence_count} occurrences 缺失</Tag> : <StatusTag status="verified" /> }]} />
          </Card>
          <Card title="Artifacts" extra={<Text type="secondary">FASTLINK / mismatch 明确展示</Text>}>
            {api.rawDownloadEnabled && <Alert className="page-alert" type="warning" showIcon message="Artifact 原始下载已启用：Phase 1 无登录 / 权限过滤，仅限受信任内网使用。" description="PE/PDB 通过短 TTL 预签名 URL 下载，请勿复制到公网或第三方工单。" />}
            <Table rowKey="id" size="small" pagination={false} dataSource={build.artifacts} scroll={{ x: 860 }} columns={[{ title: '文件', dataIndex: 'logical_name', render: (value: string) => <Text strong>{value}</Text> }, { title: '类型', dataIndex: 'kind', render: (value: string) => <Tag>{value.toUpperCase()}</Tag> }, { title: 'Verification', dataIndex: 'verification_status', render: (value: VerificationStatus) => <StatusTag status={value} /> }, { title: 'debug_id', dataIndex: 'debug_id', render: (value: string | null) => <HashValue value={value} /> }, { title: 'SHA-256', dataIndex: 'sha256', render: (value: string) => <HashValue value={value} /> }, { title: '下载', key: 'download', render: (_, row) => <Tooltip title={api.rawDownloadEnabled ? '下载短 TTL 预签名 URL' : 'RAW_DOWNLOAD_DISABLED'}><span><Button type="link" icon={<DownloadOutlined />} disabled={!api.rawDownloadEnabled} loading={downloadArtifactId === row.id} onClick={() => void downloadArtifact(row.id)}>{api.rawDownloadEnabled ? '下载' : '已禁用'}</Button></span></Tooltip> }]} />
          </Card>
        </Space>}
      </Col>
    </Row>
    <CreateBuildModal workspace={workspace} open={createOpen} onClose={() => setCreateOpen(false)} onCreated={setSelectedBuildId} />
  </div>
}
