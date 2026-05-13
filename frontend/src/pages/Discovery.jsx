import React, { useState, useEffect, useCallback } from 'react'
import { Search, RefreshCw, TrendingUp, TrendingDown, DollarSign } from 'lucide-react'
import { API_URL } from '../services/api'
import { Card, PageHeader, Spinner, EmptyState } from '../components/common/ui'
import { usePortfolio } from '../App'

export default function Discovery() {
  const { portfolioId } = usePortfolio()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch(`${API_URL}/api/portfolios/${portfolioId}/discovery`)
      if (res.ok) setData(await res.json())
    } catch (e) {
      console.error('Discovery failed:', e)
    } finally {
      setLoading(false)
    }
  }, [portfolioId])

  useEffect(() => { fetchData() }, [fetchData])

  const eligible = data?.eligible || []
  const stats = data?.stats || {}

  return (
    <div className="space-y-6">
      <PageHeader
        title="Discovery"
        subtitle="New eligible traders not yet copied"
        actions={
          <button onClick={fetchData} className="flex items-center gap-2 px-3 py-1.5 bg-surface-800 hover:bg-surface-700 border border-surface-700 rounded-lg text-xs text-surface-300 transition-colors">
            <RefreshCw size={13} /> Scan
          </button>
        }
      />

      <div className="grid grid-cols-3 gap-4">
        <Card>
          <p className="text-xs text-surface-400 uppercase tracking-wider">Scanned</p>
          <p className="font-display text-2xl mt-1 text-white">{stats.total_scanned || 0}</p>
        </Card>
        <Card>
          <p className="text-xs text-surface-400 uppercase tracking-wider">Eligible</p>
          <p className="font-display text-2xl mt-1 text-emerald-400">{stats.eligible || 0}</p>
        </Card>
        <Card>
          <p className="text-xs text-surface-400 uppercase tracking-wider">Excluded</p>
          <p className="font-display text-2xl mt-1 text-amber-400">{stats.excluded || 0}</p>
        </Card>
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><Spinner size="lg" /></div>
      ) : eligible.length === 0 ? (
        <EmptyState icon={Search} title="No eligible traders found" description="New traders may appear after the next market scan." />
      ) : (
        <div className="space-y-3">
          {eligible.map((t, i) => (
            <Card key={t.username}>
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <span className="text-xs font-mono text-surface-500 w-5">{i + 1}.</span>
                  <div>
                    <p className="text-sm font-semibold text-white">{t.username}</p>
                    <p className="text-xs text-surface-400">
                      Score: {t.score}/100  |  Return: {t.total_return_pct >= 0 ? '+' : ''}{t.total_return_pct.toFixed(1)}%  |  Risk: {t.risk_score.toFixed(1)}/10
                    </p>
                  </div>
                </div>
                <div className="text-right shrink-0">
                  <p className="text-xs text-surface-400">Min Copy</p>
                  <p className="text-sm font-mono text-surface-200">${t.min_copy_amount?.toFixed(0) || '200'}</p>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
