import { Alert, Button, Card, Descriptions, Space, Spin, Tag, Typography } from 'antd'
import { CopyOutlined, DownloadOutlined } from '@ant-design/icons'
import { useArtifactProducers } from '../api/hooks'
import type { Workspace } from '../types'
import { PageTitle } from '../components/ui'

const { Paragraph, Text } = Typography

export function DeveloperAccessPage({ workspace }: { workspace: Workspace }) {
  const { data: producers, isLoading, isError } = useArtifactProducers()
  const msvc = producers?.find((producer) => producer.producer === 'msvc')
  const apiUrl = `${window.location.origin}/api/v1`
  const command = `crashcap --api-url ${apiUrl} init --workspace ${workspace.name} --artifact-root deploy/bin --profile release`

  return <div>
    <PageTitle kicker={`${workspace.display_name} / DEVELOPER`} title="开发者接入" description="在本机编译完成后，用统一 CLI 校验并发布精确的 EXE / DLL / PDB。Crash-Cap 不执行构建，也不上传源码。" />
    <Space direction="vertical" size={18} style={{ width: '100%' }}>
      <Card title="1. 下载 crashcap">
        <Space wrap>
          <Button type="primary" icon={<DownloadOutlined />} href="/downloads/crashcap/windows-x86_64/crashcap.exe">Windows x64</Button>
          <Button icon={<DownloadOutlined />} href="/downloads/crashcap/release.json">release.json</Button>
          <Button icon={<DownloadOutlined />} href="/downloads/crashcap/SHA256SUMS">SHA256SUMS</Button>
        </Space>
        <Alert style={{ marginTop: 16 }} type="warning" showIcon message="签名边界" description="内部试点可按 SHA-256 校验；release.json 标记为 unsigned-pilot 时，不得用于正式推广。正式版本必须验证组织 Authenticode 签名、签名后哈希与证书指纹。" />
      </Card>
      <Card title="2. 初始化当前 Workspace">
        <Paragraph copyable={{ text: command, icon: [<CopyOutlined key="copy" />, <CopyOutlined key="copied" />] }} code>{command}</Paragraph>
        <Text type="secondary">命令会确认 Workspace、扫描 deploy/bin 并生成可提交的 crashcap.toml；存在多个 EXE 时需显式指定 --entrypoint。</Text>
      </Card>
      <Card title="3. 校验并发布">
        <Paragraph code>crashcap validate --profile release</Paragraph>
        <Paragraph code>crashcap doctor</Paragraph>
        <Paragraph code>crashcap publish --profile release</Paragraph>
        <Text type="secondary">成功后生成不含凭据、源码路径和预签名 URL 的 crashcap-publication.json。</Text>
      </Card>
      <Card title="服务兼容性">
        {isLoading ? <Spin /> : isError ? <Alert type="error" showIcon message="无法读取 Artifact Producer 能力" /> : <Descriptions size="small" column={{ xs: 1, md: 2 }}>
          <Descriptions.Item label="Build Publication">{msvc?.build_publications_enabled ? <Tag color="green">已启用</Tag> : <Tag color="orange">部署开关关闭</Tag>}</Descriptions.Item>
          <Descriptions.Item label="Producer">{msvc ? <Tag color="green">MSVC · {msvc.status}</Tag> : '未注册'}</Descriptions.Item>
          <Descriptions.Item label="Artifact profile">{msvc?.artifact_format ?? '—'}</Descriptions.Item>
          <Descriptions.Item label="最低客户端版本">{msvc?.minimum_client_version ?? '—'}</Descriptions.Item>
        </Descriptions>}
      </Card>
    </Space>
  </div>
}
