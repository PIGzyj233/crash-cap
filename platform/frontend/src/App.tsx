import { App as AntApp,ConfigProvider } from 'antd'
import zhCN from 'antd/locale/zh_CN'
import { useEffect } from 'react'
import { Navigate,Route,Routes,useNavigate,useParams } from 'react-router-dom'
import { ErrorBoundary } from './components/ErrorBoundary'
import { RouteEffects } from './components/RouteEffects'
import { PlatformLayout } from './layouts/PlatformLayout'
import { WorkspaceLayout,useWorkspaceRoute } from './layouts/WorkspaceLayout'
import { ArtifactPage } from './pages/ArtifactPage'
import { DeveloperAccessPage } from './pages/DeveloperAccessPage'
import { GroupPage } from './pages/GroupPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { OccurrenceInboxPage } from './pages/OccurrenceInboxPage'
import { OccurrenceReport } from './pages/OccurrenceReport'
import { PlatformHomePage } from './pages/PlatformHomePage'
import { SymbolHealthPage } from './pages/SymbolHealthPage'
import { UploadPage } from './pages/UploadPage'
import { WorkspaceDirectoryPage } from './pages/WorkspaceDirectoryPage'
import { WorkspaceOverviewPage } from './pages/WorkspaceOverviewPage'
import { routePaths } from './routes/routePaths'
import { migrateLegacyWorkspaceStorage } from './routes/workspaceStorage'
import { antdTheme } from './theme/antdTheme'

export function App() {
  useEffect(() => { migrateLegacyWorkspaceStorage() }, [])
  return <ConfigProvider theme={antdTheme} locale={zhCN}><AntApp><ErrorBoundary><RouteEffects /><Routes>
    <Route element={<PlatformLayout />}>
      <Route index element={<PlatformHomePage />} />
      <Route path="workspaces" element={<WorkspaceDirectoryPage />} />
      <Route path="upload" element={<UploadPage />} />
      <Route path="artifacts" element={<ArtifactPage />} />
    </Route>
    <Route path="w/:workspaceId" element={<WorkspaceLayout />}>
      <Route index element={<Navigate to="overview" replace />} />
      <Route path="overview" element={<OverviewRoute />} />
      <Route path="occurrences" element={<OccurrenceInboxPage />} />
      <Route path="occurrences/:occurrenceId" element={<OccurrenceRoute />} />
      <Route path="upload" element={<WorkspaceUploadRoute />} />
      <Route path="artifacts" element={<ArtifactRoute />} />
      <Route path="symbols" element={<SymbolRoute />} />
      <Route path="groups" element={<GroupRoute />} />
      <Route path="groups/:groupId" element={<GroupRoute />} />
      <Route path="developer" element={<DeveloperRoute />} />
      <Route path="*" element={<NotFoundPage />} />
    </Route>
    <Route path="*" element={<NotFoundPage />} />
  </Routes></ErrorBoundary></AntApp></ConfigProvider>
}

function OverviewRoute() {
  const workspace = useWorkspaceRoute()
  const navigate = useNavigate()
  return <WorkspaceOverviewPage workspace={workspace} onOpenOccurrence={(id) => navigate(routePaths.occurrence(workspace.id, id))} onOpenGroup={(id) => navigate(routePaths.group(workspace.id, id))} />
}

function OccurrenceRoute() {
  const workspace = useWorkspaceRoute()
  const { occurrenceId = '' } = useParams<{ occurrenceId: string }>()
  const navigate = useNavigate()
  return <OccurrenceReport workspace={workspace} occurrenceId={occurrenceId} onBack={() => navigate(routePaths.occurrences(workspace.id))} onOpenGroup={(id) => navigate(routePaths.group(workspace.id, id))} />
}

function WorkspaceUploadRoute() { return <UploadPage workspace={useWorkspaceRoute()} /> }
function ArtifactRoute() { return <ArtifactPage workspace={useWorkspaceRoute()} /> }

function SymbolRoute() {
  const workspace = useWorkspaceRoute()
  return <SymbolHealthPage workspace={workspace} />
}

function GroupRoute() {
  const workspace = useWorkspaceRoute()
  const { groupId } = useParams<{ groupId: string }>()
  return <GroupPage workspace={workspace} initialGroupId={groupId} />
}

function DeveloperRoute() {
  return <DeveloperAccessPage workspace={useWorkspaceRoute()} />
}
