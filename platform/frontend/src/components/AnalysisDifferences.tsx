import { useState } from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'
import { Alert, Button, Space, Table, Typography } from 'antd'
import { useApi } from '../api/context'

function valueText(value: unknown): string {
  return value === null ? '无' : typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}

export function AnalysisDifferences({ workspaceId, occurrenceId, runId }: { workspaceId: string; occurrenceId: string; runId: string }) {
  const api = useApi()
  const [open, setOpen] = useState(false)
  const query = useInfiniteQuery({
    queryKey: ['analysis-differences', workspaceId, occurrenceId, runId], initialPageParam: 0,
    queryFn: ({ pageParam }) => api.getAnalysisDifferences(workspaceId, occurrenceId, runId, pageParam),
    getNextPageParam: (page) => page.next_offset ?? undefined, enabled: open, retry: false,
  })
  const rows = query.data?.pages.flatMap((page) => page.items).map((row, index) => ({ ...row, index })) ?? []
  const renderValue = (value: unknown) => <pre style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', margin: 0 }}>{valueText(value)}</pre>
  return <Space direction="vertical" style={{ width: '100%' }}>
    <Button size="small" onClick={() => setOpen(!open)}>{open ? '收起证据差异' : '查看证据差异'}</Button>
    {open && <>
      <Typography.Text type="secondary">以下是当次选择记录的差异，不是两份报告的完整文本比较。未记录差异不代表报告完全相同。</Typography.Text>
      {query.isError && <Alert type="warning" message="证据差异暂时无法读取" action={<Button onClick={() => void (query.isFetchNextPageError ? query.fetchNextPage() : query.refetch())}>重试</Button>} />}
      <Table rowKey="index" size="small" pagination={false} tableLayout="fixed" scroll={{ x: 540 }} dataSource={rows} loading={query.isFetching && !query.isFetchingNextPage} locale={{ emptyText: query.data ? '该次决策未记录逐项差异' : query.isError ? '差异内容尚未取得' : '正在读取差异' }} columns={[
        { title: '比较位置', dataIndex: 'path', width: 180, render: (value: string) => <span style={{ overflowWrap: 'anywhere' }}>{value}</span> },
        { title: '原报告依据', dataIndex: 'before', width: 120, render: renderValue },
        { title: '此次报告依据', dataIndex: 'after', width: 240, render: renderValue },
      ]} />
      {query.hasNextPage && <Button onClick={() => void query.fetchNextPage()} loading={query.isFetchingNextPage}>加载更多差异</Button>}
    </>}
  </Space>
}
