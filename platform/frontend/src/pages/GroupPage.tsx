import { ArrowRightOutlined,PartitionOutlined } from '@ant-design/icons'
import { Alert,Card,List,Space,Tag,Typography } from 'antd'
import { useEffect,type ReactNode } from 'react'
import { Link,useNavigate } from 'react-router-dom'
import { CrashCapApiError } from '../api/client'
import { useGroup,useGroups } from '../api/hooks'
import { DataTable } from '../components/DataTable'
import { MasterDetail } from '../components/MasterDetail'
import { FRAME_ROW_KEY,frameColumns,withFrameKeys,type KeyedFrame } from '../components/frameColumns'
import { EmptyState,ErrorState,HashValue,LoadingState,PageTitle,StatusTag } from '../components/ui'
import { routePaths } from '../routes/routePaths'
import type { CrashGroup,Workspace } from '../types'

const { Text } = Typography

export function GroupPage({ workspace, initialGroupId }: { workspace: Workspace; initialGroupId?: string }) {
  const navigate = useNavigate()
  const { data: groups, isLoading: groupsLoading, isError: groupsError, refetch: refetchGroups } = useGroups(workspace.id)
  const id = initialGroupId ?? groups?.[0]?.id
  const { data: group, error: groupLoadError, isLoading: groupLoading, isError: groupError, refetch: refetchGroup } = useGroup(id)

  useEffect(() => {
    if (!initialGroupId && groups?.[0]) navigate(routePaths.group(workspace.id, groups[0].id), { replace: true })
  }, [groups, initialGroupId, navigate, workspace.id])

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
    groupDetail = groupLoadError instanceof CrashCapApiError && groupLoadError.status === 404
      ? <Card><Alert type="error" showIcon message="Exact Group 不存在" description={`未找到 ${id}，不会静默选择其他 Group。`} /></Card>
      : <Card><ErrorState description="Exact Group 详情加载失败" onRetry={() => void refetchGroup()} /></Card>
  } else if (group.workspace_id !== workspace.id) {
    groupDetail = <Card><Alert type="error" showIcon message="Exact Group 不属于当前 Workspace" description={`URL Workspace=${workspace.id}，资源声明 Workspace=${group.workspace_id}；平台不会静默切换。`} /></Card>
  } else {
    groupDetail = (
      <Space direction="vertical" style={{ width: '100%' }} size={24}>
        <Card
          title={<span><PartitionOutlined /> {group.title}</span>}
          extra={<Tag color="purple">Exact</Tag>}
        >
          <Space direction="vertical" size={16} style={{ width: '100%' }}>
            <Alert
              type="success"
              showIcon
              message="这个组有足够的 Exact 证据"
              description={<span>代表栈包含 {group.representative_stack.filter((frame) => frame.in_app).length} 个业务帧。版本分布使用每个 DMP 的当前标签。</span>}
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
            columns={frameColumns<KeyedFrame<CrashGroup['representative_stack'][number]>>()}
            minWidth={760}
          />
        </Card>

        <Card title="版本分布">
          <DataTable
            rowKey={(row) => row.version ?? "__undeclared"}
            dataSource={group.version_distribution}
            minWidth={560}
            columns={[
              { title: 'Version', dataIndex: 'version', width: 200, render: (value) => value ?? '未声明版本' },
              { title: 'Occurrence', dataIndex: 'count', width: 130, align: 'right', className: 'cc-num' },
            ]}
          />
        </Card>

        <Card title="组内 Occurrence">
          <List
            dataSource={group.occurrence_ids}
            renderItem={(occurrenceId) => (
              <List.Item actions={[<Link to={routePaths.occurrence(workspace.id, occurrenceId)}>打开报告 <ArrowRightOutlined /></Link>]}>
                <Text code>{occurrenceId}</Text>
              </List.Item>
            )}
          />
        </Card>

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
                <List.Item className={item.id === id ? 'build-list-item selected' : 'build-list-item'}>
                  <Link className="collection-row-link" to={routePaths.group(workspace.id, item.id)}><List.Item.Meta avatar={<div className="group-index">{item.occurrence_count}</div>} title={item.title} description={<Space><StatusTag status={item.status} /><HashValue value={item.fingerprint} length={14} /></Space>} /></Link>
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
        description="按精确故障模块和可靠业务栈归组，查看相同崩溃的发生次数与版本分布。"
      />
      <MasterDetail master={groupList} detail={groupDetail} />
    </div>
  )
}
