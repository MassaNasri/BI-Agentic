import { useMemo } from 'react'

import AnimatedPage from '../../components/AnimatedPage'
import { useAuthStore } from '../../store/auth'
import SubscriptionPlansPanel from '../../components/subscription/SubscriptionPlansPanel'

function SubscriptionPlansPage() {
  const { user, workspace } = useAuthStore()

  const workspaceId = useMemo(() => {
    if (workspace?.id) return workspace.id
    if (user?.workspace?.id) return user.workspace.id
    if (Array.isArray(workspace) && workspace.length > 0) return workspace[0]?.id || null
    return null
  }, [workspace, user])

  return (
    <AnimatedPage>
      <div className="space-y-6">
        <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-blue-700">Billing</p>
          <h1 className="mt-2 text-3xl font-semibold text-slate-900">Workspace Subscription</h1>
          <p className="mt-2 text-sm text-slate-600">
            Upgrade your workspace with voice limits, MCP access, and advanced capabilities.
          </p>
        </div>

        <SubscriptionPlansPanel workspaceId={workspaceId} />
      </div>
    </AnimatedPage>
  )
}

export default SubscriptionPlansPage
