import { Col, Row } from 'antd'
import type { ReactNode } from 'react'

/**
 * The master/detail split shared by the Build and Exact Group pages.
 *
 * `lg={9}` rather than `8`: between 992px and 1200px an 8/16 split leaves the
 * master list too narrow for a version string plus its status tags.
 */
export function MasterDetail({ master, detail }: { master: ReactNode; detail: ReactNode }) {
  return (
    <Row gutter={[24, 24]}>
      <Col xs={24} lg={9} xl={8}>{master}</Col>
      <Col xs={24} lg={15} xl={16}>{detail}</Col>
    </Row>
  )
}
