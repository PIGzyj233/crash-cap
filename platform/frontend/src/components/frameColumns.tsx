import { Tag, Tooltip, Typography } from 'antd'
import type { TableColumnsType } from 'antd'
import { PathText, SymbolText, TrustTag } from './ui'
import type { FrameTrust } from '../types'

const { Text } = Typography

/** Windows dumps commonly carry an absolute image path; the basename is the
 * identifying part users need to scan, while the full path remains available
 * below it and in the tooltip. */
export function moduleBasename(value: string | null | undefined): string | null {
  if (!value) return null
  const normalized = value.replaceAll('\\', '/')
  return normalized.slice(normalized.lastIndexOf('/') + 1) || value
}

/**
 * The fields both frame representations share.
 *
 * Canonical frames (`CanonicalFrame`) and a group's representative stack
 * (`CanonicalFrameResponse`) are separate generated types: the latter models
 * `inline` as nullable. Accepting the looser shape lets one column set serve
 * both without casting either away.
 */
export interface FrameLike {
  index: number
  module?: string | null
  function?: string | null
  file?: string | null
  line?: number | null
  trust: FrameTrust
  in_app: boolean
  inline?: boolean | null
}

/**
 * Shared column set for the two stack-frame tables (the Crash Stack tab and a
 * group's representative stack). They had already drifted — one rendered the
 * inline/in_app distinction and the other rendered neither — so the definition
 * lives here to keep them honest.
 *
 * Column order and meaning are fixed by docs/design.md §12.3:
 * index / module / function / source / trust.
 */
export function frameColumns<T extends FrameLike>(): TableColumnsType<T> {
  return [
    { title: '#', dataIndex: 'index', width: 52, fixed: 'left', className: 'cc-num' },
    {
      title: 'Module',
      dataIndex: 'module',
      width: 220,
      render: (value: string | null, row: T) => (
        <span className="frame-module">
          <span className="frame-module-name"><Text strong>{moduleBasename(value) ?? '未知模块'}</Text>{row.in_app && <Tag color="blue" className="frame-app-tag">app</Tag>}</span>
          {value && moduleBasename(value) !== value && <Tooltip title={value}><Text type="secondary" className="frame-module-path">{value}</Text></Tooltip>}
        </span>
      ),
    },
    {
      title: 'Function',
      dataIndex: 'function',
      render: (value: string | null, row: T) => (
        <span>
          {value ? <SymbolText value={value} /> : <Text type="secondary">未符号化</Text>}
          {row.inline && <Tag color="purple" className="frame-app-tag">inline</Tag>}
        </span>
      ),
    },
    {
      title: 'Source',
      key: 'source',
      width: 200,
      render: (_, row: T) => <PathText file={row.file} line={row.line} />,
    },
    // Pinned right: trust is the one column that must never be scrolled out of
    // sight, because `scan` frames MUST stay visibly low-confidence
    // (docs/design.md §14.2).
    { title: 'Trust', dataIndex: 'trust', width: 116, fixed: 'right', render: (value: FrameTrust) => <TrustTag trust={value} /> },
  ]
}

/**
 * Annotates frames with a stable, unique row key.
 *
 * Inline frames reuse both the `index` and the `instruction_addr` of the
 * physical frame they expand (`core/src/canonical.rs` passes the same `frame`
 * and `index` to every inline record), so neither is unique and keying on them
 * silently drops rows. Array position is the only stable discriminator, and
 * antd deprecates the `index` argument of a `rowKey` function — so the position
 * is baked in here and referenced by field name.
 */
export const FRAME_ROW_KEY = 'frameRowKey'

/** A frame carrying its precomputed unique row key. */
export type KeyedFrame<T extends FrameLike> = T & { frameRowKey: string }

export function withFrameKeys<T extends FrameLike>(frames: readonly T[]): KeyedFrame<T>[] {
  return frames.map((frame, position) => ({ ...frame, frameRowKey: `${frame.index}-${position}` }))
}
