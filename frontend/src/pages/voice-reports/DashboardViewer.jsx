import { Navigate, useLocation } from 'react-router-dom'

function DashboardViewer() {
  const location = useLocation()
  return <Navigate to={`/dashboard${location.search || ''}`} replace />
}

export default DashboardViewer
