import { Collapse, Space, Tag, Typography } from 'antd'
import type { components } from '../generated/openapi'
import { CatalogOrigins } from './CatalogOrigins'

type Selection = components['schemas']['Canonical11Module']['selection']
type Outcomes = components['schemas']['Canonical11Module']['source_outcomes']
const states = { none: '未找到配对', unique: '唯一配对', conflict: '身份冲突', unavailable: '配对不可用', indeterminate: '尚不能确定' }
const reasons = {
  missing: '没有匹配的完整配对', unique: '冻结选择得到唯一可用配对', identity_conflict: '同一捕获身份存在不同内容，需要提供方复核',
  withdrawn: '配对已逻辑停用', location_unavailable: '配对材料不可读', incomplete_identity: '捕获身份不完整',
  enumeration_failed: '候选枚举未完成', validation_incomplete: '候选验证未完成',
}

export function ModuleSymbolSelection({ selection, outcomes = [] }: { selection: Selection; outcomes?: Outcomes }) {
  const ids = [...new Set([...selection.candidate_pair_ids, ...selection.unavailable_pair_ids, ...(selection.selected_pair_id ? [selection.selected_pair_id] : [])])]
  const pdb = outcomes.filter((row) => row.stage === 'download_pdb')
  const loaded = pdb.filter((row) => row.outcome === 'found')
  const sourceName = (id: string) => id === 'crash-cap:microsoft' ? 'Microsoft 官方符号源' : id.startsWith('crash-cap:pair:') ? '已导入配对' : id
  return <Space direction="vertical">
    <Typography.Text>{loaded.length ? `PDB 已加载 · ${[...new Set(loaded.map((row) => sourceName(row.source_id)))].join('、')}` : pdb.length ? 'PDB 未加载' : 'PDB 未记录请求结果'}</Typography.Text>
    {!loaded.length && pdb.map((row, index) => <Typography.Text key={index} type="secondary">{sourceName(row.source_id)}：{row.reason}</Typography.Text>)}
    <Collapse size="small" items={[{
    key: 'selection', label: states[selection.state], children: <Space direction="vertical">
      <Typography.Text>{reasons[selection.reason]}</Typography.Text>
      {selection.state === 'none' && <Typography.Text type="secondary">未找到导入配对不代表公共 PDB 未加载；PDB 结果见上方。PE 是否参与栈展开另行判断。</Typography.Text>}
      <Typography.Text type="secondary">这是该次分析冻结的选择；来源窗口显示当前目录记录，不修改历史结果。</Typography.Text>
      {!selection.candidates_complete && <Typography.Text type="warning">候选尚未枚举完整，以下列表不能证明匹配唯一。</Typography.Text>}
      {ids.map((id, index) => <Space key={id} wrap>
        <Typography.Text>配对 {index + 1}</Typography.Text>
        {id === selection.selected_pair_id && <Tag color="green">该次选用</Tag>}
        {selection.unavailable_pair_ids.includes(id) && <Tag>该次不可用</Tag>}
        <CatalogOrigins pairId={id} />
      </Space>)}
      {ids.length === 0 && <Typography.Text type="secondary">该次未记录候选配对</Typography.Text>}
    </Space>,
  }]} /></Space>
}
