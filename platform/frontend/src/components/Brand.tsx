import { Link } from 'react-router-dom'

export function Brand() {
  return <Link to="/" className="app-brand" aria-label="Crash-Cap 平台概览">
    <span className="app-brand-mark" aria-hidden="true">C</span>
    <span className="app-brand-name">Crash-Cap</span>
  </Link>
}
