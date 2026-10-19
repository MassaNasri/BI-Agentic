import { useCallback, useEffect, useState } from 'react'
import { Check, ShieldCheck } from 'lucide-react'
import { toast } from 'react-hot-toast'

import Card from '../Card'
import { subscriptionAPI } from '../../api/endpoints'

const currencyFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency', currency: 'USD', maximumFractionDigits: 2,
})

function normalizeFeatures(features) {
  if (Array.isArray(features)) return features.map(String).filter(Boolean)
  if (features && typeof features === 'object') {
    return Object.entries(features).filter(([, value]) => Boolean(value))
      .map(([key, value]) => value === true ? key : `${key}: ${value}`)
  }
  if (typeof features === 'string') return features.split(/[,\n]/).map((item) => item.trim()).filter(Boolean)
  return []
}

function SubscriptionPlansPanel({ workspaceId, title = 'Choose Your Plan' }) {
  const [plans, setPlans] = useState([])
  const [currentSubscription, setCurrentSubscription] = useState(null)
  const [loading, setLoading] = useState(true)

  const loadPlans = useCallback(async () => {
    setLoading(true)
    try {
      const plansResponse = await subscriptionAPI.listPlans()
      setPlans(plansResponse.data?.plans || [])
      if (workspaceId) {
        const currentResponse = await subscriptionAPI.getCurrentSubscription(workspaceId)
        setCurrentSubscription(currentResponse.data?.subscription || null)
      }
    } catch (error) {
      toast.error(error.response?.data?.message || 'Failed to load subscription plans')
    } finally {
      setLoading(false)
    }
  }, [workspaceId])

  useEffect(() => { loadPlans() }, [loadPlans])

  return (
    <div className="space-y-6">
      <Card>
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-brand-300">Subscription</p>
        <h2 className="mt-2 text-2xl font-semibold text-white">{title}</h2>
        <p className="mt-2 text-sm text-[var(--c-muted)]">
          Paid activation is unavailable until secure checkout is configured. No card or bank details are collected here.
        </p>
      </Card>
      {currentSubscription && (
        <Card>
          <div className="flex items-center gap-2 text-brand-300"><ShieldCheck className="h-4 w-4" /> Current plan</div>
          <h3 className="mt-2 text-lg font-semibold text-white">{currentSubscription.plan?.name}</h3>
          <p className="text-sm text-[var(--c-muted)]">Active until {currentSubscription.end_date || 'N/A'}.</p>
        </Card>
      )}
      {loading ? <Card><p className="text-sm text-[var(--c-muted)]">Loading plans...</p></Card> : (
        <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          {plans.map((plan) => (
            <Card key={plan.id}>
              {plan.badge && <p className="text-xs font-medium text-brand-300">{plan.badge}</p>}
              <h3 className="mt-2 text-xl font-semibold text-white">{plan.name}</h3>
              <p className="mt-2 text-sm text-[var(--c-muted)]">{plan.description}</p>
              <p className="mt-4 text-2xl font-bold text-white">{currencyFormatter.format(Number(plan.price_monthly || 0))} <span className="text-sm font-normal">/ month</span></p>
              <p className="mt-2 text-sm text-brand-300">{plan.max_voice_requests} voice requests &middot; {plan.duration_days} days</p>
              <ul className="mt-4 space-y-2 text-sm text-brand-300">
                {normalizeFeatures(plan.features).map((feature) => (
                  <li key={feature} className="flex items-start gap-2"><Check className="mt-0.5 h-4 w-4" />{feature}</li>
                ))}
              </ul>
              <p className="mt-5 text-sm font-medium text-[var(--c-muted)]">
                {currentSubscription?.plan?.id === plan.id ? 'Current plan' : 'Checkout coming soon'}
              </p>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}

export default SubscriptionPlansPanel
