import { createBrowserRouter, Navigate } from 'react-router-dom'
import { AppLayout } from './AppLayout'
import { ProjectListPage } from '@/pages/ProjectListPage'
import { ProjectWorkspacePage } from '@/pages/ProjectWorkspacePage'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <Navigate to="/projects" replace /> },
      { path: 'projects', element: <ProjectListPage /> },
      { path: 'projects/:projectId', element: <ProjectWorkspacePage /> },
    ],
  },
])
