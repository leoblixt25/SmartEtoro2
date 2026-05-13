import React, { useState, useEffect, useCallback } from 'react'
import { Activity, RefreshCw, Users } from 'lucide-react'
import { API_URL } from '../services/api'
import { Card, PageHeader, Spinner, EmptyState } from '../components/common/ui'
import { usePortfolio } from '../App'

export default function Health() {
  const { portfolioId } = usePortfolio()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  const fetchHealth = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_URL}/api/portfolios/${portfolioId}/dashboard`)
      if (res.ok) setData(await res.json())
    } catch (e) {
      console.error('Health fetch failed:', e)
    } finally {
      setLoading(false)
    }
  }, [portfolioId])

  useEffect(() => { fetchHealth() }, [fetchHealth])

  const traders = data?.active_traders || []

  return (
    <div className="space-y-6">
      <PageHeader
        title="Trader Health"
        subtitle="Performance and risk overview for all active traders"
        actions={
          <button onClick={fetchHealth} className="flex items-center gap-2 px-3 py-1.5 bg-surface-800 hover:bg-surface-700 border border-surface-700 rounded-lg text-xs text-surface-300 transition-colors">
            <RefreshCw size={13} /> Refresh
          </button>
        }
      />

      {loading ? (
        <div className="flex justify-center py-12"><Spinner size="lg" /></div>
      ) : traders.length === 0 ? (
        <EmptyState icon={Users} title="No active traders" description="Add copied traders to see health analysis." />
      ) : (
        <div className="space-y-4">
          {traders.map(t => {
            const ret = t.total_return_pct || 0
            const risk = t.risk_score || 5
            const dd = t.max_drawdown || 0

            const healthLabel = ret > 10 && risk < 5 ? 'Healthy'
              : ret > 0 && risk < 7 ? 'Stable'
              : ret < -10 || risk > 7 ? 'At Risk'
              : 'Watch'

            const healthColor = healthLabel === 'Healthy' ? 'text-emerald-400'
              : healthLabel === 'At Risk' ? 'text-red-400'
              : healthLabel === 'Stable' ? 'text-emerald-300'
              : 'text-amber-400'

            return (
              <Card key={t.id}>
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-surface-700 flex items-center justify-center">
                      <span className="text-sm font-mono font-bold text-surface-300">
                        {t.username.slice(0, 2).toUpperCase()}
                      </span>
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <h3 className="font-semibold text-white">{t.username}</h3>
                        <span className={`text-xs font-medium ${healthColor}`}>{healthLabel}</span>
                      </div>
                      <div className="flex items-center gap-3 mt-1 text-xs text-surface-400">
                        <span>
                          Allocation: <span className="text-surface-200">{t.allocation_pct.toFixed(1)}%</span>
                        </span>
                        <span>
                          Invested: <span className="text-surface-200">${(t.allocated_amount || 0).toLocaleString()}</span>
                        </span>
                      </div>
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <p className={`text-sm font-mono ${ret >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                      {ret >= 0 ? '+' : ''}{ret.toFixed(2)}%
                    </p>
                    <p className={`text-xs ${risk >= 7 ? 'text-red-400' : 'text-surface-400'}`}>
                      Risk: {risk.toFixed(1)}/10
                    </p>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-3 mt-4 pt-4 border-t border-surface-800">
                  <div className="text-center">
                    <p className="text-xs text-surface-500">Return</p>
                    <p className={`text-sm font-mono mt-0.5 ${ret >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                      {ret >= 0 ? '+' : ''}{ret.toFixed(2)}%
                    </p>
                  </div>
                  <div className="text-center">
                    <p className="text-xs text-surface-500">Drawdown</p>
                    <p className={`text-sm font-mono mt-0.5 ${dd > 20 ? 'text-red-400' : 'text-amber-400'}`}>
                      {dd.toFixed(1)}%
                    </p>
                  </div>
                  <div className="text-center">
                    <p className="text-xs text-surface-500">Health</p>
                    <p className={`text-sm font-mono mt-0.5 ${healthColor}`}>{healthLabel}</p>
                  </div>
                </div>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
