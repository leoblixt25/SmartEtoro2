import React, { useState, useEffect, useCallback } from 'react'
import { DollarSign, TrendingUp, TrendingDown, Activity, RefreshCw, AlertTriangle, Users, Search } from 'lucide-react'
import { portfolioAPI, tradersAPI, alertsAPI, API_URL } from '../services/api'
import { Card, PageHeader, StatCard, Spinner, EmptyState } from '../components/common/ui'
import { usePortfolio } from '../App'

export default function Overview() {
  const { portfolioId } = usePortfolio()
  const [dashboard, setDashboard] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await portfolioAPI.dashboard(portfolioId)
      setDashboard(data)
    } catch (e) {
      setError('Failed to load portfolio data.')
    } finally {
      setLoading(false)
    }
  }, [portfolioId])

  useEffect(() => { fetchData() }, [fetchData])

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <div className="text-center">
        <Spinner size="lg" />
        <p className="text-surface-400 text-sm mt-3">Loading portfolio...</p>
      </div>
    </div>
  )

  if (error) return (
    <div className="flex items-center justify-center h-64">
      <div className="text-center max-w-sm">
        <AlertTriangle size={28} className="text-amber-400 mx-auto mb-3" />
        <p className="text-white font-medium mb-1">Connection Error</p>
        <p className="text-surface-400 text-sm">{error}</p>
        <button onClick={fetchData} className="mt-4 px-4 py-2 bg-brand-500 text-white rounded-lg text-sm hover:bg-brand-600 transition-colors">
          Retry
        </button>
      </div>
    </div>
  )

  const overview = dashboard?.portfolio_overview || {}
  const active = dashboard?.active_traders || []
  const alerts = dashboard?.alerts || {}

  return (
    <div className="space-y-6">
      <PageHeader
        title="Portfolio Overview"
        subtitle={`Last sync: ${overview.last_sync ? new Date(overview.last_sync).toLocaleString() : '\u2014'}`}
        actions={
          <button onClick={fetchData} className="flex items-center gap-2 px-3 py-1.5 bg-surface-800 hover:bg-surface-700 border border-surface-700 rounded-lg text-xs text-surface-300 transition-colors">
            <RefreshCw size={13} /> Refresh
          </button>
        }
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard label="Total Value" value={`$${(overview.total_value || 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}`} icon={DollarSign} />
        <StatCard label="Available Cash" value={`$${(overview.available_cash || 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}`} icon={DollarSign} />
        <StatCard label="Total Return" value={`${(overview.total_return_pct || 0).toFixed(2)}%`} icon={(overview.total_return_pct || 0) >= 0 ? TrendingUp : TrendingDown} colorClass={(overview.total_return_pct || 0) >= 0 ? 'bg-emerald-500/15' : 'bg-red-500/15'} />
        <StatCard label="Health Score" value={`${(overview.health_score || 0).toFixed(0)}/100`} icon={Activity} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-white">Active Traders</h3>
            <span className="text-xs text-surface-400">{overview.active_traders || 0} of {overview.total_traders || 0}</span>
          </div>
          {active.length === 0 ? (
            <EmptyState icon={Users} title="No active traders" />
          ) : (
            <div className="space-y-3">
              {active.slice(0, 6).map(t => (
                <div key={t.id} className="flex items-center justify-between py-2 border-b border-surface-800 last:border-0">
                  <div>
                    <p className="text-sm text-white">{t.username}</p>
                    <p className="text-xs text-surface-400">{t.allocation_pct.toFixed(1)}% allocated</p>
                  </div>
                  <div className="text-right">
                    <p className={`text-sm font-mono ${t.total_return_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                      {t.total_return_pct >= 0 ? '+' : ''}{t.total_return_pct.toFixed(2)}%
                    </p>
                    <p className="text-xs text-surface-500">risk {t.risk_score.toFixed(1)}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card>
          <h3 className="text-sm font-semibold text-white mb-4">Status</h3>
          <div className="space-y-3">
            <div className="flex justify-between py-2 border-b border-surface-800">
              <span className="text-sm text-surface-400">Sentiment</span>
              <span className={`text-sm font-medium ${overview.sentiment === 'positive' ? 'text-emerald-400' : overview.sentiment === 'negative' ? 'text-red-400' : 'text-amber-400'}`}>
                {overview.sentiment || 'neutral'}
              </span>
            </div>
            <div className="flex justify-between py-2 border-b border-surface-800">
              <span className="text-sm text-surface-400">Concentration Risk</span>
              <span className={`text-sm font-medium ${overview.concentration_risk ? 'text-red-400' : 'text-emerald-400'}`}>
                {overview.concentration_risk ? 'Yes' : 'No'}
              </span>
            </div>
            <div className="flex justify-between py-2 border-b border-surface-800">
              <span className="text-sm text-surface-400">Unrealized PnL</span>
              <span className={`text-sm font-mono ${(overview.unrealized_pnl || 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                ${(overview.unrealized_pnl || 0).toFixed(2)}
              </span>
            </div>
            <div className="flex justify-between py-2">
              <span className="text-sm text-surface-400">Currency</span>
              <span className="text-sm text-surface-200">{overview.currency || 'USD'}</span>
            </div>
          </div>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <h3 className="text-sm font-semibold text-white mb-4">Recent Alerts</h3>
          {!alerts.recent || alerts.recent.length === 0 ? (
            <EmptyState icon={AlertTriangle} title="No recent alerts" description="All clear — no new notifications." />
          ) : (
            <div className="space-y-2">
              {alerts.recent.map(a => (
                <div key={a.id} className="flex items-start gap-2 p-2 rounded-lg bg-surface-800">
                  <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${a.severity === 'critical' ? 'bg-red-500/20 text-red-400' : a.severity === 'warning' ? 'bg-amber-500/20 text-amber-400' : 'bg-blue-500/20 text-blue-400'}`}>
                    {a.severity}
                  </span>
                  <div className="min-w-0">
                    <p className="text-xs text-white truncate">{a.title}</p>
                    <p className="text-xs text-surface-400 truncate">{a.message}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card>
          <h3 className="text-sm font-semibold text-white mb-4">Discovery</h3>
          <div className="flex items-center justify-center h-32 text-center">
            <div>
              <Search size={24} className="text-surface-500 mx-auto mb-2" />
              <p className="text-sm text-surface-400">
                {dashboard?.discovery?.eligible?.length || 0} eligible traders found
              </p>
              <p className="text-xs text-surface-500 mt-1">
                {dashboard?.discovery?.stats?.total_scanned || 0} scanned
              </p>
            </div>
          </div>
        </Card>
      </div>
    </div>
  )
}
