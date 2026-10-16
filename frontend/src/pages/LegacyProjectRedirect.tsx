import { Navigate, useParams } from 'react-router-dom'
import { sectionPath } from '@/shared/project/sections'

export function LegacyProjectRedirect() {
  const { repo, project } = useParams()
  return <Navigate to={sectionPath('apis', repo && project ? `${repo}/${project}` : undefined)} replace />
}
