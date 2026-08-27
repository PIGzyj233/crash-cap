import { useEffect, useState, type ReactNode } from 'react'
import { Alert, Button, Card, List, Space, Tag, Typography } from 'antd'
import { ArrowRightOutlined, PartitionOutlined } from '@ant-design/icons'
import { useGroup, useGroups } from '../api/hooks'
import type { Workspace } from '../types'
import { DataTable } from '../components/DataTable'
import { MasterDetail } from '../components/MasterDetail'
import { FRAME_ROW_KEY, frameColumns, withFrameKeys } from '../components/frameColumns'
import { EmptyState, ErrorState, HashValue, LoadingState, PageTitle, StatusTag } from '../components/ui'

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
      groupDetail = <Card><LoadingState rows={4} /></Card>
    } else if (groupsError) {
      // `Exact Groups 加载失败` MUST render here AND in the list panel below:
      // CollectionPages.test.tsx:226 asserts findAllByText(...).length === 2.
      // Do not consolidate these two call sites.
      groupDetail = <Card><ErrorState description="Exact Groups 加载失败" onRetry={() => void refetchGroups()} /></Card>
    } else {
      groupDetail = <Card><EmptyState description="暂无 Exact Group；证据不足的 Occurrence 会保留为 Unclassified" /></Card>
    }
  } else if (groupLoading) {
    groupDetail = <Card><LoadingState rows={4} /></Card>
  } else if (groupError || !group) {
    // Exactly one retry button in this branch — CollectionPages.test.tsx:245
    // uses a singular getByRole, which throws when two match.
    groupDetail = <Card><ErrorState description="Exact Group 详情加载失败" onRetry={() => void refetchGroup()} /></Card>
  } else {
    groupDetail = (
      <Space direction="vertical" style={{ width: '100%' }} size={24}>
        <Card
          title={<span><PartitionOutlined /> {group.title}</span>}
          extra={<Tag color="purple">Exact · exact-v1.0</Tag>}
        >
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Alert
              type="success"
              showIcon
              message="这个组有足够的 Exact 证据"
              description={<span>代表栈来自 {group.representative_stack.length} 个业务帧；相似度固定为 1.0。Version 只用于分布展示。</span>}
            />
            <Space wrap>
              <Tag>Occurrences {group.occurrence_count}</Tag>
              <Tag>First seen {new Date(group.first_seen).toLocaleString('zh-CN')}</Tag>
              <Tag>Last seen {new Date(group.last_seen).toLocaleString('zh-CN')}</Tag>
              <StatusTag status={group.status} />
            </Space>
          </Space>
        </Card>

        <Card title="代表性栈">
          <DataTable
            rowKey={FRAME_ROW_KEY}
            dataSource={withFrameKeys(group.representative_stack)}
            columns={frameColumns()}
            minWidth={760}
          />
        </Card>

        <Card title="Build 分布">
          <DataTable
            rowKey="build_id"
            dataSource={group.build_distribution}
            minWidth={560}
            columns={[
              { title: 'Version', dataIndex: 'version', width: 200 },
              { title: 'Build', dataIndex: 'build_id', render: (value: string) => <HashValue value={value} length={18} /> },
              { title: 'Occurrence', dataIndex: 'count', width: 130, align: 'right', className: 'cc-num' },
            ]}
          />
        </Card>

        <Card title="组内 Occurrence">
          <List
            dataSource={group.occurrence_ids}
            renderItem={(occurrenceId) => (
              <List.Item actions={[<Button type="link" onClick={() => onOpenOccurrence(occurrenceId)}>打开报告 <ArrowRightOutlined /></Button>]}>
                <Text code>{occurrenceId}</Text>
              </List.Item>
            )}
          />
        </Card>

        <Alert type="info" showIcon message="merge / split 未实现" description="Phase 1 保留组的非破坏性元数据接口；人工 merge/split 属于后续阶段。" />
      </Space>
    )
  }

  const groupList = (
    <Card title="Groups" className="section-card" styles={{ body: { padding: 0 } }}>
      {groupsLoading ? <LoadingState rows={3} />
        : groupsError
          // Second of the two required `Exact Groups 加载失败` sites — see the
          // comment on the detail branch above before touching this.
          ? <ErrorState description="Exact Groups 加载失败" onRetry={() => void refetchGroups()} />
          : (
            <List
              dataSource={groups ?? []}
              locale={{ emptyText: '没有 Exact Group；Unclassified 不建伪组' }}
              renderItem={(item) => (
                <List.Item
                  className={item.id === id ? 'build-list-item selected' : 'build-list-item'}
                  onClick={() => setSelectedId(item.id)}
                >
                  <List.Item.Meta
                    avatar={<div className="group-index">{item.occurrence_count}</div>}
                    title={item.title}
                    description={<Space><StatusTag status={item.status} /><HashValue value={item.fingerprint} length={14} /></Space>}
                  />
                </List.Item>
              )}
            />
          )}
    </Card>
  )

  return (
    <div>
      <PageTitle
        kicker={`${workspace.display_name} / EXACT GROUPS`}
        title="Exact Groups"
        description="仅展示满足精确故障模块与非 scan 业务帧证据的组；Phase 1 不提供 Family、merge 或 split。"
      />
      <MasterDetail master={groupList} detail={groupDetail} />
    </div>
  )
}
