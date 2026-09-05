import type { TableProps } from 'antd'
import { Table } from 'antd'

/**
 * Table with overflow containment on by default.
 *
 * rc-table only emits an `overflow-x: auto` wrapper when `scroll.x` is set, so
 * a table without it cannot scroll — an unbreakable token (a mangled C++
 * symbol, a SHA-256) instead widens the <table> past its column and bursts the
 * surrounding card. Defaulting `scroll.x` here makes the safe behaviour the
 * default rather than something each new call site has to remember.
 *
 * Note `scroll.x` also switches the layout to `table-layout: fixed` when any
 * column is fixed, and <colgroup> only emits a <col> for columns with an
 * explicit `width` — so columns still need widths, or they divide the remaining
 * space evenly and look cramped.
 */
export function DataTable<T extends object>({ minWidth = 720, ...props }: TableProps<T> & { minWidth?: number }) {
  return <Table<T> size="small" pagination={false} {...props} scroll={{ x: minWidth, ...props.scroll }} />
}
