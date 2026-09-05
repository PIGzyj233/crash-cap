import { useInfiniteQuery,useQueryClient } from '@tanstack/react-query'
import { Alert,Button,Collapse,Space,Table,Tag,Typography } from 'antd'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useApi } from '../api/context'
import { AnalysisDifferences } from './AnalysisDifferences'
import { ResultReviewForm } from './ResultReviewForm'
import { ResultReviews } from './ResultReviews'

const decisions = { promote: '采用此报告', retain: '保留原报告', incomparable: '需要复核', correct: '已纠正原报告' }
const reasons: Record<string, string> = {
  initial: '首次可用报告', improved: '补充了证据并保留原有依据', equivalent: '证据等价',
  candidate_not_eligible: '此次结果不满足采用条件', older_candidate: '已有更新的报告',
  verified_correction: '已验证的证据纠正', reviewed_transition: '经过复核的上下文变更',
  transition_requires_review: '分析条件发生变化，需要复核', legacy_evidence_missing: '旧报告缺少比较依据',
  candidate_evidence_missing: '此次报告缺少比较依据', module_evidence_incomplete: '模块依据不完整',
  pair_evidence_incomplete: '配对验证依据不完整', context_mismatch: '分析上下文不一致',
  fault_changed: '故障位置依据改变', ambiguous_alignment: '新旧调用栈无法唯一对齐',
  unwind_changed: '调用栈展开依据改变', interpretation_changed: '已有函数或源码解释改变',
  correction_required: '配对变化需要纠正复核', selection_evidence_incomplete: '符号选择依据不完整',
  unknown_loss: '存在无法解释的证据缺失', permanent_loss: '已有证据永久缺失',
  business_transient_loss: '业务模块证据暂时不可用', system_transient_loss: '系统模块证据暂时不可用',
  non_system_transient_loss: '非系统模块证据暂时不可用', q16_system_transient: '满足允许的系统模块暂时缺失条件',
  occurrence_or_dump_mismatch: '事故或 DMP 身份不一致',
}

export function AnalysisHistory({ workspaceId, occurrenceId }: { workspaceId: string; occurrenceId: string }) {
  const api = useApi()
  const queryClient = useQueryClient()
  const reviewSaved = () => {
    for (const queryKey of [
      ['analysis-history', workspaceId, occurrenceId], ['result-reviews', workspaceId, occurrenceId],
      ['occurrence', occurrenceId], ['occurrences'], ['groups', workspaceId], ['symbol-health', workspaceId],
    ]) void queryClient.invalidateQueries({ queryKey })
    for (const section of ['occurrence-analysis', 'occurrence-threads', 'occurrence-modules']) {
      void queryClient.invalidateQueries({ queryKey: [section, occurrenceId, undefined], exact: true })
    }
  }
  const [expanded, setExpanded] = useState(false)
  const history = useInfiniteQuery({
    queryKey: ['analysis-history', workspaceId, occurrenceId], initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => api.getAnalysisHistory(workspaceId, occurrenceId, pageParam),
    getNextPageParam: (page) => page.next_cursor ?? undefined, enabled: expanded, retry: false,
    refetchInterval: expanded ? 5000 : false,
  })
  const rows = history.data?.pages.flatMap((page) => page.items) ?? []
  const currentId = history.data?.pages[0]?.current_run_id
  const path = `/w/${encodeURIComponent(workspaceId)}/occurrences/${encodeURIComponent(occurrenceId)}`
  return <Collapse onChange={(keys) => setExpanded(keys.includes('runs'))} items={[{
    key: 'runs', label: '分析历史与报告选择依据', children: <Space direction="vertical" style={{ width: '100%' }}>
      <Typography.Text type="secondary">选择依据记录当次分析完成时的决定；当前报告以 Current 标记为准。历史报告保持原始结果。</Typography.Text>
      {history.isError && <Alert type="warning" message="分析历史暂时无法读取" action={<Button onClick={() => void (history.isFetchNextPageError ? history.fetchNextPage() : history.refetch())}>重试</Button>} />}
      <Table rowKey="id" dataSource={rows} pagination={false} tableLayout="fixed" loading={history.isFetching && !history.isFetchingNextPage} scroll={{ x: 1140 }} columns={[
        { title: '报告', key: 'report', width: 280, render: (_, row) => <Space direction="vertical" style={{ overflowWrap: 'anywhere' }}>{row.report_available ? <Link to={`${path}?run=${encodeURIComponent(row.id)}`}>{row.id}</Link> : <Typography.Text>{row.id}</Typography.Text>}{row.id === currentId && <Tag color="green">Current</Tag>}</Space> },
        { title: '状态', dataIndex: 'status', width: 90 },
        { title: '完成时间', dataIndex: 'finished_at', width: 170, render: (value: string | null) => value ? new Date(value).toLocaleString() : '尚未完成' },
        { title: '当次选择依据', key: 'selection', width: 600, render: (_, row) => row.selection ? <Space direction="vertical" style={{ width: '100%' }}>
          <Typography.Text>{decisions[row.selection.decision]}：{reasons[row.selection.reason] ?? `尚未翻译的原因：${row.selection.reason}`}</Typography.Text>
          {row.selection.observed_current_run_id && <Link to={`${path}?run=${encodeURIComponent(row.selection.observed_current_run_id)}`}>查看当时的原报告</Link>}
          <AnalysisDifferences workspaceId={workspaceId} occurrenceId={occurrenceId} runId={row.id} />
          {currentId && row.schema_version === '2.0' && row.report_available && <ResultReviewForm workspaceId={workspaceId} occurrenceId={occurrenceId} currentRunId={currentId} candidateRunId={row.id} onSaved={reviewSaved} />}
        </Space> : '未记录选择依据' },
      ]} />
      <Space><Button onClick={() => void history.refetch()} loading={history.isRefetching}>刷新分析历史</Button>{history.hasNextPage && <Button onClick={() => void history.fetchNextPage()} loading={history.isFetchingNextPage}>加载更多分析</Button>}</Space>
      <ResultReviews workspaceId={workspaceId} occurrenceId={occurrenceId} />
    </Space>,
  }]} />
}
