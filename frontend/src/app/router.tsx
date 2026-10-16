import { createBrowserRouter, Navigate } from 'react-router-dom'
import { RequireAuth } from '@/features/auth/RequireAuth'
import { ProjectListPage } from '@/pages/ProjectListPage'
import { ProjectWorkspacePage } from '@/pages/ProjectWorkspacePage'
import { AppLayout } from './AppLayout'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      {
        element: <RequireAuth />,
        children: [
          { index: true, element: <Navigate to="/projects" replace /> },
          { path: 'projects', element: <ProjectListPage /> },
          // 两段式：与后端 /repos/{repo}/projects/{project} 主键 {repo}/{project} 对齐
          { path: 'projects/:repo/:project', element: <ProjectWorkspacePage /> },
        ],
      },
    ],
  },
])
