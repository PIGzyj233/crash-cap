import { UploadHistoryPage } from './pages/UploadHistoryPage'
import { useEffect } from 'react'
import { Navigate,Route,Routes,useNavigate,useParams } from 'react-router-dom'
import { ErrorBoundary } from './components/ErrorBoundary'
import { AccountPage, AdminUsersPage } from './pages/AccountPage'
import { RouteEffects } from './components/RouteEffects'
import { PlatformLayout } from './layouts/PlatformLayout'
import { WorkspaceLayout,useWorkspaceRoute } from './layouts/WorkspaceLayout'
import { ArtifactDetailPage,ArtifactPage } from './pages/ArtifactPage'
import { DeveloperAccessPage } from './pages/DeveloperAccessPage'
import { GroupPage } from './pages/GroupPage'
import { NotFoundPage } from './pages/NotFoundPage'
import { OccurrenceInboxPage } from './pages/OccurrenceInboxPage'
import { OccurrenceReport } from './pages/OccurrenceReport'
import { PlatformHomePage } from './pages/PlatformHomePage'
import { SymbolHealthPage,SymbolIssuePage } from './pages/SymbolHealthPage'
import { UploadPage } from './pages/UploadPage'
import { WorkspaceDirectoryPage } from './pages/WorkspaceDirectoryPage'
import { WorkspaceOverviewPage } from './pages/WorkspaceOverviewPage'
import { routePaths } from './routes/routePaths'
import { migrateLegacyWorkspaceStorage } from './routes/workspaceStorage'

export function App() {
  useEffect(() => { migrateLegacyWorkspaceStorage() }, [])
  return <ErrorBoundary><RouteEffects /><Routes>
    <Route element={<PlatformLayout />}>
      <Route index element={<PlatformHomePage />} />
      <Route path="uploads" element={<UploadHistoryPage />} />
      <Route path="account" element={<AccountPage />} />
      <Route path="admin/users" element={<AdminUsersPage />} />
      <Route path="workspaces" element={<WorkspaceDirectoryPage />} />
      <Route path="upload" element={<UploadPage />} />
      <Route path="artifacts" element={<ArtifactPage />} />
      <Route path="artifacts/:artifactId" element={<ArtifactDetailPage />} />
      <Route path="*" element={<NotFoundPage />} />
    </Route>
    <Route path="w/:workspaceId" element={<WorkspaceLayout />}>
      <Route index element={<Navigate to="overview" replace />} />
      <Route path="overview" element={<OverviewRoute />} />
      <Route path="occurrences" element={<OccurrenceInboxPage />} />
      <Route path="occurrences/:occurrenceId" element={<OccurrenceRoute />} />
      <Route path="upload" element={<WorkspaceUploadRoute />} />
      <Route path="artifacts" element={<ArtifactRoute />} />
      <Route path="artifacts/:artifactId" element={<ArtifactDetailRoute />} />
      <Route path="symbols" element={<SymbolRoute />} />
      <Route path="symbols/:issueId" element={<SymbolIssueRoute />} />
      <Route path="groups" element={<GroupRoute />} />
      <Route path="groups/:groupId" element={<GroupRoute />} />
      <Route path="developer" element={<DeveloperRoute />} />
      <Route path="*" element={<NotFoundPage />} />
    </Route>
  </Routes></ErrorBoundary>
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
function ArtifactDetailRoute() { return <ArtifactDetailPage workspace={useWorkspaceRoute()} /> }
function SymbolIssueRoute() { return <SymbolIssuePage workspace={useWorkspaceRoute()} /> }

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
