import { useInfiniteQuery } from '@tanstack/react-query';
import { Alert,Button,Collapse,Space,Table,Typography } from 'antd';
import { useState } from 'react';
import { useApi } from '../api/context';

export function SubmissionHistory({ workspaceId, occurrenceId }: { workspaceId: string; occurrenceId: string }) {
  const api = useApi()
  const [expanded, setExpanded] = useState(false)
  const history = useInfiniteQuery({
    queryKey: ['submission-history', workspaceId, occurrenceId],
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => api.getSubmissions(workspaceId, occurrenceId, pageParam),
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    enabled: expanded,
    retry: false,
  })
  const rows = history.data?.pages.flatMap((page) => page.items) ?? []
  const different = new Set(rows.map((row) => JSON.stringify([row.label, row.batch]))).size > 1
  return <Collapse onChange={(keys) => setExpanded(keys.includes('history'))} items={[{
    key: 'history', label: '提交记录与人工测试标注', children: <Space direction="vertical" style={{ width: '100%' }}>
      <Typography.Text type="secondary">人工标注用于追踪测试来源，不代表已验证的 Build，也不参与符号匹配。旧上传可能没有提交记录。</Typography.Text>
      {different && <Alert type="info" showIcon message="已加载的提交包含不同版本或批次标注，各次原始标注均保留。" />}
      {history.isError && <Alert type="warning" message="提交记录暂时无法读取" action={<Button onClick={() => void (history.isFetchNextPageError ? history.fetchNextPage() : history.refetch())}>重试</Button>} />}
      <Table rowKey="upload_id" dataSource={rows} loading={history.isFetching && !history.isFetchingNextPage} pagination={false} scroll={{ x: 900 }} locale={{ emptyText: '暂无已验证的提交记录' }} columns={[
        { title: '测试版本（人工）', dataIndex: 'label', render: (value: string | null) => value ?? '未填写' },
        { title: '批次（人工）', dataIndex: 'batch', render: (value: string | null) => value ?? '未填写' },
        { title: '来源', dataIndex: 'source' },
        { title: '文件名', dataIndex: 'filename' },
        { title: '提交时间', dataIndex: 'submitted_at', render: (value: string) => new Date(value).toLocaleString() },
        { title: '验证时间', dataIndex: 'verified_at', render: (value: string) => new Date(value).toLocaleString() },
      ]} />
      <Space><Button onClick={() => void history.refetch()} loading={history.isRefetching}>刷新记录</Button>{history.hasNextPage && <Button onClick={() => void history.fetchNextPage()} loading={history.isFetchingNextPage}>加载更多提交</Button>}</Space>
    </Space>,
  }]} />
}
