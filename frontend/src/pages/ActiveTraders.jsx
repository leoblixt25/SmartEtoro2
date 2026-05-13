import React, { useState, useEffect, useCallback } from 'react'
import { Users, RefreshCw, TrendingUp, TrendingDown } from 'lucide-react'
import { tradersAPI } from '../services/api'
import { Card, PageHeader, Badge, PnlDisplay, Spinner, EmptyState } from '../components/common/ui'
import { usePortfolio } from '../App'

export default function ActiveTraders() {
  const { portfolioId } = usePortfolio()
  const [traders, setTraders] = useState([])
  const [loading, setLoading] = useState(true)

  const fetchTraders = useCallback(async () => {
    setLoading(true)
    try {
      const data = await tradersAPI.active(portfolioId)
      setTraders(data)
    } catch (e) {
      console.error('Failed to load traders:', e)
    } finally {
      setLoading(false)
    }
  }, [portfolioId])

  useEffect(() => { fetchTraders() }, [fetchTraders])

  return (
    <div className="space-y-6">
      <PageHeader
        title="Active Traders"
        subtitle={`${traders.length} copied trader${traders.length !== 1 ? 's' : ''} being monitored`}
        actions={
          <button onClick={fetchTraders} className="flex items-center gap-2 px-3 py-1.5 bg-surface-800 hover:bg-surface-700 border border-surface-700 rounded-lg text-xs text-surface-300 transition-colors">
            <RefreshCw size={13} /> Refresh
          </button>
        }
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <p className="text-xs text-surface-400 uppercase tracking-wider">Total</p>
          <p className="font-display text-2xl mt-1 text-white">{traders.length}</p>
        </Card>
        <Card>
          <p className="text-xs text-surface-400 uppercase tracking-wider">Active</p>
          <p className="font-display text-2xl mt-1 text-emerald-400">{traders.filter(t => !t.is_paused).length}</p>
        </Card>
        <Card>
          <p className="text-xs text-surface-400 uppercase tracking-wider">Paused</p>
          <p className="font-display text-2xl mt-1 text-amber-400">{traders.filter(t => t.is_paused).length}</p>
        </Card>
        <Card>
          <p className="text-xs text-surface-400 uppercase tracking-wider">Avg Risk</p>
          <p className={`font-display text-2xl mt-1 ${traders.length ? (traders.reduce((s, t) => s + t.risk_score, 0) / traders.length >= 7 ? 'text-red-400' : 'text-emerald-400') : 'text-surface-400'}`}>
            {traders.length ? (traders.reduce((s, t) => s + t.risk_score, 0) / traders.length).toFixed(1) : '\u2014'}
          </p>
        </Card>
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><Spinner size="lg" /></div>
      ) : traders.length === 0 ? (
        <EmptyState icon={Users} title="No active traders" description="Add copied traders to start monitoring." />
      ) : (
        <div className="space-y-3">
          {traders.map(t => {
            const riskColor = t.risk_score >= 7 ? 'text-red-400' : t.risk_score >= 5 ? 'text-amber-400' : 'text-emerald-400'
            return (
              <Card key={t.id}>
                <div className="flex items-start gap-4">
                  <div className="w-10 h-10 rounded-xl bg-surface-700 flex items-center justify-center shrink-0">
                    <span className="text-sm font-mono font-bold text-surface-300">
                      {t.username.slice(0, 2).toUpperCase()}
                    </span>
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="font-semibold text-white">{t.username}</h3>
                      {t.is_paused && <Badge variant="yellow">Paused</Badge>}
                    </div>
                    <div className="flex items-center gap-4 mt-1 flex-wrap text-xs">
                      <span className="text-surface-400">
                        Allocated: <span className="text-surface-200">${(t.allocated_amount || 0).toLocaleString()}</span>
                        <span className="text-surface-500"> ({t.allocation_pct.toFixed(1)}%)</span>
                      </span>
                      <span className="text-surface-400">
                        Return: <span className={t.total_return_pct >= 0 ? 'text-emerald-400' : 'text-red-400'}>
                          {t.total_return_pct >= 0 ? '+' : ''}{t.total_return_pct.toFixed(2)}%
                        </span>
                      </span>
                      <span className="text-surface-400">
                        Risk: <span className={riskColor}>{t.risk_score.toFixed(1)}/10</span>
                      </span>
                      <span className="text-surface-400">
                        DD: <span className="text-surface-300">{t.max_drawdown.toFixed(1)}%</span>
                      </span>
                    </div>
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
