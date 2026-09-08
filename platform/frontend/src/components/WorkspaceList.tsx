import { ArrowRightOutlined,PlusOutlined } from '@ant-design/icons'
import { App as AntApp,Button,Card,Form,Input,Modal,Spin,Tag,Typography } from 'antd'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { routePaths } from '../routes/routePaths'
import { useCreateWorkspace,useWorkspaces } from '../api/hooks'
import type { Workspace } from '../types'
import { EmptyState,ErrorState,PageTitle } from './ui'

const { Text } = Typography

export function WorkspaceList({ onSelect }: { onSelect: (workspace: Workspace) => void }) {
  const { data: workspaces, isLoading, isError, refetch } = useWorkspaces()
  const createWorkspace = useCreateWorkspace()
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [form] = Form.useForm<{ name: string; display_name?: string }>()
  const { message } = AntApp.useApp()

  const submit = async () => {
    try {
      const input = await form.validateFields()
      const created = await createWorkspace.mutateAsync(input)
      setOpen(false)
      form.resetFields()
      onSelect(created)
      message.success('工作空间已创建')
    } catch (error) {
      if (error instanceof Error && error.message !== 'Validation Failed') message.error(error.message)
    }
  }

  return (
    <div className="workspace-landing">
      <PageTitle title="工作空间" description="按项目组织崩溃报告、符号文件与团队分析。" extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>创建工作空间</Button>} />
      <Input.Search aria-label="搜索工作空间" placeholder="搜索空间名称" value={search} onChange={event => setSearch(event.target.value)} allowClear className="section-card" style={{ maxWidth: 360 }} />
      {isLoading ? <div className="center-state"><Spin size="large" /></div> : isError ? <ErrorState description="工作空间加载失败" onRetry={() => void refetch()} /> : !workspaces?.length ? <Card><EmptyState description="还没有工作空间" action={<Button type="primary" onClick={() => setOpen(true)}>创建第一个工作空间</Button>} /></Card> : (
        <div className="workspace-grid">
          {workspaces.filter(workspace => `${workspace.name} ${workspace.display_name ?? ''}`.toLowerCase().includes(search.trim().toLowerCase())).map((workspace) => <Link key={workspace.id} className="workspace-card-link" to={routePaths.overview(workspace.id)}><Card className="workspace-card" hoverable>
            <div className="workspace-card-top"><div className="workspace-glyph">{(workspace.display_name ?? workspace.name).slice(0, 1).toUpperCase()}</div><Tag color="geekblue">{workspace.platform}</Tag></div>
            <Typography.Title level={3}>{workspace.display_name ?? workspace.name}</Typography.Title>
            <Text type="secondary">{workspace.name}</Text>
            <div className="workspace-card-footer"><Text type="secondary">{workspace.default_architecture} · 保留 {workspace.retention_days} 天</Text><ArrowRightOutlined /></div>
          </Card></Link>)}
          {workspaces.length > 0 && !workspaces.some(workspace => `${workspace.name} ${workspace.display_name ?? ''}`.toLowerCase().includes(search.trim().toLowerCase())) && <EmptyState description="没有符合搜索的空间" action={<Button onClick={() => setSearch('')}>清除搜索</Button>} />}
        </div>
      )}
      <Modal title="创建工作空间" open={open} okText="创建" cancelText="取消" confirmLoading={createWorkspace.isPending} onOk={submit} onCancel={() => setOpen(false)}>
        <Form form={form} layout="vertical" requiredMark="optional">
          <Form.Item name="name" label="稳定名称" rules={[{ required: true, message: '请输入稳定名称' }, { pattern: /^[a-z0-9][a-z0-9-]+$/, message: '使用小写字母、数字和连字符' }]}><Input placeholder="desktop-client" /></Form.Item>
          <Form.Item name="display_name" label="显示名称"><Input placeholder="Desktop Client" /></Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
