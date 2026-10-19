import { createBrowserRouter, Navigate } from 'react-router-dom'
import { RequireAuth } from '@/features/auth/RequireAuth'
import { ProjectListPage } from '@/pages/ProjectListPage'
import { FeatureWorkspacePage } from '@/pages/FeatureWorkspacePage'
import type { WorkspaceSection } from '@/shared/project/sections'
import { LegacyProjectRedirect } from '@/pages/LegacyProjectRedirect'
import { AppLayout } from './AppLayout'

const sections: WorkspaceSection[] = ['apis', 'pages', 'scenarios', 'configuration']
export const router = createBrowserRouter([
  {
    path: '/', element: <AppLayout />,
    children: [{
      element: <RequireAuth />,
      children: [
        { index: true, element: <Navigate to="/apis" replace /> },
        ...sections.flatMap((section) => [
          { path: section, element: <FeatureWorkspacePage section={section} /> },
          { path: `${section}/:repo/:project`, element: <FeatureWorkspacePage section={section} /> },
        ]),
        { path: 'configuration/repositories', element: <ProjectListPage /> },
        { path: 'projects', element: <Navigate to="/apis" replace /> },
        { path: 'projects/:repo/:project', element: <LegacyProjectRedirect /> },
      ],
    }],
  },
])
