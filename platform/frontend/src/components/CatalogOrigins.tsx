import { useState } from 'react'
import { useInfiniteQuery, useQueryClient } from '@tanstack/react-query'
import { Alert, Button, Modal, Space, Table, Typography } from 'antd'
import { Link } from 'react-router-dom'
import { useApi } from '../api/context'
import { CatalogReviewForm } from './CatalogReviewForm'
import { CatalogReviewHistory } from './CatalogReviewHistory'

const labels = { import_item: '独立导入', build_artifacts: 'Build 符号', publication: 'Build 发布' }

export function CatalogOrigins({ pairId }: { pairId: string }) {
  const api = useApi()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const query = useInfiniteQuery({
    queryKey: ['catalog-origins', pairId], initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) => api.getCatalogOrigins(pairId, pageParam),
    getNextPageParam: (page) => page.next_cursor ?? undefined, enabled: open, retry: false,
  })
  const rows = query.data?.pages.flatMap((page) => page.items) ?? []
  const pair = query.data?.pages[0]
  return <>
    <Button onClick={() => setOpen(true)}>查看配对来源</Button>
    <Modal open={open} onCancel={() => setOpen(false)} footer={null} title="配对来源与提供方记录" width={900}>
      <Space direction="vertical" style={{ width: '100%' }}>
        <Typography.Text>来源记录不代表当前 Workspace 的模块角色或 Build 归属。身份冲突需要提供方核对文件并提供复核依据。</Typography.Text>
        {pair && <Typography.Text type="secondary">逻辑资格：{pair.state === 'active' ? '有效' : '已停用'}。此状态不单独证明材料可读或匹配唯一。</Typography.Text>}
        {query.isError && <Alert type="warning" message="来源暂时无法读取" action={<Button onClick={() => void (query.isFetchNextPageError ? query.fetchNextPage() : query.refetch())}>重试</Button>} />}
        <Table rowKey="id" dataSource={rows} pagination={false} loading={query.isFetching && !query.isFetchingNextPage} locale={{ emptyText: query.data ? '未记录来源' : '尚未取得来源记录' }} columns={[
          { title: '来源类型', dataIndex: 'origin_type', render: (value: keyof typeof labels) => labels[value] },
          { title: '来源说明', dataIndex: 'source_label', render: (value: string | null) => value ?? '未记录' },
          { title: '提供方提交记录', key: 'link', render: (_, row) => row.import_id
            ? <Link to={`/symbol-imports?import=${encodeURIComponent(row.import_id)}`} onClick={() => setOpen(false)}>查看导入批次</Link>
            : row.build_id && row.source_workspace_id
              ? <Link to={`/w/${encodeURIComponent(row.source_workspace_id)}/builds/${encodeURIComponent(row.build_id)}`} onClick={() => setOpen(false)}>查看原 Build</Link>
              : <Typography.Text>未记录可导航的提交</Typography.Text> },
        ]} />
        {query.hasNextPage && <Button onClick={() => void query.fetchNextPage()} loading={query.isFetchingNextPage}>加载更多来源</Button>}
        {pair && <CatalogReviewHistory pairId={pairId} />}
        {pair && <CatalogReviewForm key={pairId} pairId={pairId} version={pair.qualification_version} onSaved={() => { void query.refetch(); void queryClient.invalidateQueries({ queryKey: ['catalog-review-history', pairId] }) }} />}
      </Space>
    </Modal>
  </>
}
