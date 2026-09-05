import { useInfiniteQuery,useQuery } from '@tanstack/react-query'
import { Alert,Button,Descriptions,Space,Table,Typography } from 'antd'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../api/context'

const decisions = { promote: '采用候选报告', correct: '纠正原报告', retain: '保留原报告', incomparable: '仍需复核' }
const causes = { engine_upgrade: '分析引擎升级', role_change: '模块归属变更', evidence_correction: '证据纠正' }
type Scope = { workspaceId: string; occurrenceId: string }

function ReviewEvidence({ workspaceId, occurrenceId, reviewId }: Scope & { reviewId: string }) {
  const api = useApi()
  const [open, setOpen] = useState(false)
  const evidence = useQuery({
    queryKey: ['result-review-evidence', workspaceId, occurrenceId, reviewId],
    queryFn: () => api.getResultReviewEvidence(workspaceId, occurrenceId, reviewId),
    enabled: open, retry: false,
  })
  return <Space direction="vertical" style={{ width: '100%' }}>
    <Button size="small" onClick={() => setOpen(!open)}>{open ? '收起审核依据' : '查看审核依据'}</Button>
    {open && <>
      {evidence.isPending && <Typography.Text role="status">正在读取审核依据</Typography.Text>}
      {evidence.isError && <Alert type="warning" message="审核依据暂时无法读取" action={<Button onClick={() => void evidence.refetch()}>重试</Button>} />}
      {evidence.data && <>
        <Descriptions size="small" column={1} items={[
          { key: 'time', label: '依据保存时间', children: new Date(evidence.data.created_at).toLocaleString() },
          { key: 'old', label: '原报告摘要', children: <Typography.Text copyable style={{ overflowWrap: 'anywhere' }}>{evidence.data.request.current_canonical_sha256}</Typography.Text> },
          { key: 'new', label: '候选报告摘要', children: <Typography.Text copyable style={{ overflowWrap: 'anywhere' }}>{evidence.data.request.candidate_canonical_sha256}</Typography.Text> },
        ]} />
        <Typography.Text type="secondary">提供方依据保留审核当时的状态。</Typography.Text>
        <Table rowKey="review_id" size="small" pagination={false} dataSource={evidence.data.provider_basis} locale={{ emptyText: '本次审核未引用提供方复核' }} columns={[
          { title: '提供方复核', dataIndex: 'review_id', render: (value: string) => <span style={{ overflowWrap: 'anywhere' }}>{value}</span> },
          { title: '当时状态', dataIndex: 'state', render: (value: string) => value === 'active' ? '有效' : '已停用' },
          { title: '说明', dataIndex: 'reason' },
        ]} />
      </>}
    </>}
  </Space>
}

export function ResultReviews({ workspaceId, occurrenceId }: Scope) {
  const api = useApi()
  const [open, setOpen] = useState(false)
  const reviews = useInfiniteQuery({
    queryKey: ['result-reviews', workspaceId, occurrenceId], initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => api.getResultReviews(workspaceId, occurrenceId, pageParam),
    getNextPageParam: (page) => page.next_cursor ?? undefined, enabled: open, retry: false,
  })
  const rows = reviews.data?.pages.flatMap((page) => page.items) ?? []
  const path = `/w/${encodeURIComponent(workspaceId)}/occurrences/${encodeURIComponent(occurrenceId)}`
  return <Space direction="vertical" style={{ width: '100%' }}>
    <Button onClick={() => setOpen(!open)}>{open ? '收起追加审核记录' : '查看追加审核记录'}</Button>
    {open && <>
      <Typography.Text type="secondary">这里记录报告生成后的人工审核。审核人是提交时填写的声明，当前采用的报告以 Current 标记为准。</Typography.Text>
      {reviews.isError && <Alert type="warning" message="审核记录暂时无法读取" action={<Button onClick={() => void (reviews.isFetchNextPageError ? reviews.fetchNextPage() : reviews.refetch())}>重试</Button>} />}
      <Table rowKey="id" dataSource={rows} pagination={false} tableLayout="fixed" scroll={{ x: 900 }} loading={reviews.isFetching && !reviews.isFetchingNextPage} locale={{ emptyText: reviews.data ? '尚无追加审核记录' : '审核记录尚未取得' }} columns={[
        { title: '审核结论', key: 'decision', width: 180, render: (_, row) => <Space direction="vertical"><Typography.Text>{decisions[row.decision]}</Typography.Text><Typography.Text type="secondary">{causes[row.cause]}</Typography.Text><Typography.Text>{new Date(row.created_at).toLocaleString()}</Typography.Text></Space> },
        { title: '报告', key: 'reports', width: 180, render: (_, row) => <Space direction="vertical"><Link to={`${path}?run=${encodeURIComponent(row.current_run_id)}`}>查看审核前的报告</Link><Link to={`${path}?run=${encodeURIComponent(row.candidate_run_id)}`}>查看审核候选报告</Link></Space> },
        { title: '审核说明与依据', key: 'evidence', width: 540, render: (_, row) => <Space direction="vertical" style={{ width: '100%' }}><Typography.Text>审核人声明：{row.request.reviewed_by}</Typography.Text><Typography.Paragraph style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{row.request.rationale}</Typography.Paragraph><ReviewEvidence workspaceId={workspaceId} occurrenceId={occurrenceId} reviewId={row.id} /></Space> },
      ]} />
      <Space><Button onClick={() => void reviews.refetch()} loading={reviews.isRefetching}>刷新审核记录</Button>{reviews.hasNextPage && <Button onClick={() => void reviews.fetchNextPage()} loading={reviews.isFetchingNextPage}>加载更多审核</Button>}</Space>
    </>}
  </Space>
}
