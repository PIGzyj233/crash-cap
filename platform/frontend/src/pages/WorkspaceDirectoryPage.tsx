import { useNavigate } from 'react-router-dom'
import { WorkspaceList } from '../components/WorkspaceList'
import { routePaths } from '../routes/routePaths'

export function WorkspaceDirectoryPage() {
  const navigate = useNavigate()
  return <div className="platform-page"><WorkspaceList onSelect={(workspace) => navigate(routePaths.overview(workspace.id))} /></div>
}
