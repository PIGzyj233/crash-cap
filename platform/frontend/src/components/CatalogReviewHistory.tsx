import { useState } from 'react'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { Alert, Button, Collapse, Space, Table, Typography } from 'antd'
import { useApi } from '../api/context'

function ReviewEvidence({ pairId, reviewId }: { pairId: string; reviewId: string }) {
  const api = useApi()
  const [open, setOpen] = useState(false)
  const query = useQuery({ queryKey: ['catalog-review-evidence', pairId, reviewId], queryFn: () => api.getCatalogReviewEvidence(pairId, reviewId), enabled: open, retry: false })
  return <Space direction="vertical">
    <Button size="small" loading={query.isFetching} onClick={() => setOpen(!open)}>{open ? '收起复核依据' : '查看复核依据'}</Button>
    {open && query.isError && <Alert type="warning" message="依据未能通过读取或校验" action={<Button onClick={() => void query.refetch()}>重试</Button>} />}
    {open && !query.isError && query.data && <>
      <Typography.Text>复核人声明：{query.data.reviewer}</Typography.Text>
      <Typography.Paragraph style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{query.data.evidence}</Typography.Paragraph>
    </>}
  </Space>
}

export function CatalogReviewHistory({ pairId }: { pairId: string }) {
  const api = useApi()
  const [open, setOpen] = useState(false)
  const query = useInfiniteQuery({
    queryKey: ['catalog-review-history', pairId], initialPageParam: undefined as number | undefined,
    queryFn: ({ pageParam }) => api.getCatalogReviews(pairId, pageParam),
    getNextPageParam: (page) => page.next_version ?? undefined, enabled: open, retry: false,
  })
  return <Collapse onChange={(keys) => setOpen(keys.includes('reviews'))} items={[{
    key: 'reviews', label: '已保存的复核记录', children: <Space direction="vertical" style={{ width: '100%' }}>
      {query.isError && <Alert type="warning" message="复核历史暂时无法读取" action={<Button onClick={() => void (query.isFetchNextPageError ? query.fetchNextPage() : query.refetch())}>重试</Button>} />}
      <Table rowKey="id" pagination={false} scroll={{ x: 920 }} dataSource={query.data?.pages.flatMap((page) => page.items) ?? []} loading={query.isFetching && !query.isFetchingNextPage} locale={{ emptyText: query.data ? '尚无复核记录' : '尚未取得复核记录' }} columns={[
        { title: '记录', dataIndex: 'id', width: 240 },
        { title: '结论', dataIndex: 'state', width: 100, render: (state: string) => state === 'active' ? '恢复资格' : '逻辑停用' },
        { title: '原因', dataIndex: 'reason', width: 220 },
        { title: '依据', key: 'evidence', width: 360, render: (_, row) => <ReviewEvidence pairId={pairId} reviewId={row.id} /> },
      ]} />
      <Button onClick={() => void query.refetch()}>刷新复核记录</Button>
      {query.hasNextPage && <Button onClick={() => void query.fetchNextPage()} loading={query.isFetchingNextPage}>加载更多复核</Button>}
    </Space>,
  }]} />
}
