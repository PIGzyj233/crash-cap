import { useState } from 'react'
import { App as AntApp, Button, Card, Empty, Form, Input, Modal, Space, Spin, Tag, Typography } from 'antd'
import { ArrowRightOutlined, PlusOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { useCreateWorkspace, useWorkspaces } from '../api/hooks'
import type { Workspace } from '../types'
import { PageTitle } from './ui'

const { Text } = Typography

export function WorkspaceList({ onSelect }: { onSelect: (workspace: Workspace) => void }) {
  const { data: workspaces, isLoading, isError, refetch } = useWorkspaces()
  const createWorkspace = useCreateWorkspace()
  const [open, setOpen] = useState(false)
  const [form] = Form.useForm<{ name: string; display_name?: string }>()
  const { message } = AntApp.useApp()

  const submit = async () => {
    try {
      const input = await form.validateFields()
      const created = await createWorkspace.mutateAsync(input)
      setOpen(false)
      form.resetFields()
      onSelect(created)
      message.success('Workspace 已创建')
    } catch (error) {
      if (error instanceof Error && error.message !== 'Validation Failed') message.error(error.message)
    }
  }

  return (
    <div className="workspace-landing">
      <PageTitle kicker="CRASH-CAP / PRIVATE INTRANET" title="选择 Workspace" description="匿名可信内网工作台 · 每个 Workspace 独立管理 Build、符号与 Occurrence" extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>新建 Workspace</Button>} />
      <Card className="trust-banner" bordered={false}>
        <SafetyCertificateOutlined />
        <span><strong>内网模式</strong>　无登录与权限过滤。请确保 Crash-Cap 只绑定可信内网或 VPN 地址。</span>
        <Tag color="blue">RAW 下载默认关闭</Tag>
      </Card>
      {isLoading ? <div className="center-state"><Spin size="large" /></div> : isError ? <Empty description="Workspace 加载失败"><Button onClick={() => refetch()}>重试</Button></Empty> : !workspaces?.length ? <Card><Empty description="还没有 Workspace"><Button type="primary" onClick={() => setOpen(true)}>创建第一个 Workspace</Button></Empty></Card> : (
        <div className="workspace-grid">
          {workspaces.map((workspace) => <Card key={workspace.id} className="workspace-card" hoverable onClick={() => onSelect(workspace)}>
            <div className="workspace-card-top"><div className="workspace-glyph">{(workspace.display_name ?? workspace.name).slice(0, 1).toUpperCase()}</div><Tag color="geekblue">{workspace.platform}</Tag></div>
            <Typography.Title level={3}>{workspace.display_name ?? workspace.name}</Typography.Title>
            <Text type="secondary">{workspace.name}</Text>
            <div className="workspace-card-footer"><Text type="secondary">{workspace.default_architecture} · 保留 {workspace.retention_days} 天</Text><ArrowRightOutlined /></div>
          </Card>)}
        </div>
      )}
      <Modal title="新建 Workspace" open={open} okText="创建" cancelText="取消" confirmLoading={createWorkspace.isPending} onOk={submit} onCancel={() => setOpen(false)}>
        <Form form={form} layout="vertical" requiredMark="optional">
          <Form.Item name="name" label="稳定名称" rules={[{ required: true, message: '请输入稳定名称' }, { pattern: /^[a-z0-9][a-z0-9-]+$/, message: '使用小写字母、数字和连字符' }]}><Input placeholder="desktop-client" /></Form.Item>
          <Form.Item name="display_name" label="显示名称"><Input placeholder="Desktop Client" /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
