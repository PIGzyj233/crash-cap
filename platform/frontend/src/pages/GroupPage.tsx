import { useEffect, useState, type ReactNode } from 'react'
import { Alert, Button, Card, Col, Empty, List, Row, Space, Spin, Table, Tag, Typography } from 'antd'
import { ArrowLeftOutlined, PartitionOutlined } from '@ant-design/icons'
import { useGroup, useGroups } from '../api/hooks'
import type { Workspace } from '../types'
import { HashValue, PageTitle, StatusTag, TrustTag } from '../components/ui'

const { Text } = Typography

export function GroupPage({ workspace, initialGroupId, onOpenOccurrence }: { workspace: Workspace; initialGroupId?: string; onOpenOccurrence: (occurrenceId: string) => void }) {
  const { data: groups, isLoading: groupsLoading, isError: groupsError, refetch: refetchGroups } = useGroups(workspace.id)
  const [selectedId, setSelectedId] = useState(initialGroupId)
  const id = selectedId ?? groups?.[0]?.id
  const { data: group, isLoading: groupLoading, isError: groupError, refetch: refetchGroup } = useGroup(id)

  useEffect(() => { if (!selectedId && groups?.[0]) setSelectedId(groups[0].id) }, [groups, selectedId])

  let groupDetail: ReactNode
  if (!id) {
    if (groupsLoading) {
      groupDetail = <Card><div className="center-state"><Spin /></div></Card>
    } else if (groupsError) {
      groupDetail = <Card><div className="center-state"><Empty description="Exact Groups 加载失败"><Button onClick={() => void refetchGroups()}>重试</Button></Empty></div></Card>
    } else {
      groupDetail = <Card><div className="center-state"><Empty description="暂无 Exact Group；证据不足的 Occurrence 会保留为 Unclassified" /></div></Card>
    }
  } else if (groupLoading) {
    groupDetail = <Card><div className="center-state"><Spin /></div></Card>
  } else if (groupError || !group) {
    groupDetail = <Card><div className="center-state"><Empty description="Exact Group 详情加载失败"><Button onClick={() => void refetchGroup()}>重试</Button></Empty></div></Card>
  } else {
    groupDetail = <Space direction="vertical" style={{ width: '100%' }} size={18}>
      <Card title={<span><PartitionOutlined /> {group.title}</span>} extra={<Tag color="purple">Exact · exact-v1.0</Tag>}><Space direction="vertical" size={12} style={{ width: '100%' }}><Alert type="success" showIcon message="这个组有足够的 Exact 证据" description={<span>代表栈来自 {group.representative_stack.length} 个业务帧；相似度固定为 1.0。Version 只用于分布展示。</span>} /><Space wrap><Tag>Occurrences {group.occurrence_count}</Tag><Tag>First seen {new Date(group.first_seen).toLocaleString('zh-CN')}</Tag><Tag>Last seen {new Date(group.last_seen).toLocaleString('zh-CN')}</Tag><StatusTag status={group.status} /></Space></Space></Card>
      <Card title="代表性栈"><Table rowKey="index" pagination={false} size="small" dataSource={group.representative_stack} columns={[{ title: '#', dataIndex: 'index', width: 60 }, { title: 'Module', dataIndex: 'module' }, { title: 'Function', dataIndex: 'function', render: (value: string | null) => value ?? '—' }, { title: 'Source', key: 'source', render: (_, row) => row.file ? `${row.file}:${row.line ?? '—'}` : '—' }, { title: 'Trust', dataIndex: 'trust', render: (value) => <TrustTag trust={value} /> }]} /></Card>
      <Card title="Build 分布"><Table rowKey="build_id" pagination={false} size="small" dataSource={group.build_distribution} columns={[{ title: 'Version', dataIndex: 'version' }, { title: 'Build', dataIndex: 'build_id', render: (value: string) => <HashValue value={value} length={18} /> }, { title: 'Occurrence', dataIndex: 'count', align: 'right' }]} /></Card>
      <Card title="组内 Occurrence"><List dataSource={group.occurrence_ids} renderItem={(occurrenceId) => <List.Item actions={[<Button type="link" onClick={() => onOpenOccurrence(occurrenceId)}>打开报告 <ArrowLeftOutlined /></Button>]}><Text code>{occurrenceId}</Text></List.Item>} /></Card>
      <Alert type="info" showIcon message="merge / split 未实现" description="Phase 1 保留组的非破坏性元数据接口；人工 merge/split 属于后续阶段。" />
    </Space>
  }

  return <div>
    <PageTitle kicker={`${workspace.display_name} / EXACT GROUPS`} title="Exact Groups" description="仅展示满足精确故障模块与非 scan 业务帧证据的组；Phase 1 不提供 Family、merge 或 split。" />
    <Row gutter={[18, 18]}>
      <Col xs={24} lg={8}><Card title="Groups" className="section-card" styles={{ body: { padding: 0 } }}>{groupsLoading ? <div className="center-state"><Spin /></div> : groupsError ? <div className="center-state"><Empty description="Exact Groups 加载失败"><Button onClick={() => void refetchGroups()}>重试</Button></Empty></div> : <List dataSource={groups ?? []} locale={{ emptyText: '没有 Exact Group；Unclassified 不建伪组' }} renderItem={(item) => <List.Item className={item.id === id ? 'build-list-item selected' : 'build-list-item'} onClick={() => setSelectedId(item.id)}><List.Item.Meta avatar={<div className="group-index">{item.occurrence_count}</div>} title={item.title} description={<Space><StatusTag status={item.status} /><HashValue value={item.fingerprint} length={14} /></Space>} /></List.Item>} />}</Card></Col>
      <Col xs={24} lg={16}>{groupDetail}</Col>
    </Row>
  </div>
}
