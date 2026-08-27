import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render } from '@testing-library/react'
import { App as AntApp, ConfigProvider } from 'antd'
import { DataTable } from './DataTable'
import { FRAME_ROW_KEY, frameColumns, withFrameKeys, type FrameLike } from './frameColumns'

afterEach(() => cleanup())

/**
 * Inline frames reuse the physical frame's `index` AND `instruction_addr`
 * (core/src/canonical.rs), so keying on either drops rows. The mock fixture
 * only ever produces one frame per index, which is why this needs its own
 * fixture rather than relying on the page tests.
 */
const COLLIDING_FRAMES: FrameLike[] = [
  { index: 7, module: 'app.exe', function: 'Outer::Run', file: 'run.cpp', line: 10, trust: 'cfi', in_app: true, inline: false },
  { index: 7, module: 'app.exe', function: 'Inner::Step', file: 'run.cpp', line: 22, trust: 'cfi', in_app: true, inline: true },
  { index: 7, module: 'app.exe', function: 'Leaf::Emit', file: 'run.cpp', line: 31, trust: 'cfi', in_app: true, inline: true },
]

const MANGLED = 'boost::asio::detail::completion_handler<XRtcStreamer::onProcessControlMessage::$_2::<lambda_1>, boost::asio::io_context::basic_executor_type<std::allocator<void>, 0>>::do_complete'

function renderFrames(frames: FrameLike[]) {
  return render(
    <ConfigProvider>
      <AntApp>
        <DataTable rowKey={FRAME_ROW_KEY} dataSource={withFrameKeys(frames)} columns={frameColumns()} minWidth={860} />
      </AntApp>
    </ConfigProvider>,
  )
}

describe('frame table', () => {
  it('renders every inline frame even when index and address collide', () => {
    const { container } = renderFrames(COLLIDING_FRAMES)
    expect(container.querySelectorAll('tbody tr.ant-table-row').length).toBe(3)
    expect(new Set(withFrameKeys(COLLIDING_FRAMES).map((frame) => frame.frameRowKey)).size).toBe(3)
  })

  it('contains long mangled symbols instead of widening the table', () => {
    const { container } = renderFrames([{ ...COLLIDING_FRAMES[0], function: MANGLED }])
    // scroll.x gives the table an explicit width plus `min-width: 100%`, which
    // is what lets it scroll horizontally. Without it the table has no width at
    // all and an unbreakable symbol widens it until the card bursts.
    expect(container.querySelector('.ant-table-content')).toBeTruthy()
    const tableStyle = container.querySelector('table')?.getAttribute('style') ?? ''
    expect(tableStyle).toContain('width: 860px')
    expect(tableStyle).toContain('min-width: 100%')
    // The rendered cell is truncated; the full value stays available on hover.
    expect(container.textContent).not.toContain(MANGLED)
    expect(container.querySelector('.cc-symbol')?.textContent).toContain('…')
  })
})
