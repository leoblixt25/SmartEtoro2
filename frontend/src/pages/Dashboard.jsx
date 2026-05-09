/**
 * Dashboard Page
 * Main portfolio overview: value, PnL, health, charts, positions.
 */

import React, { useState, useEffect, useCallback } from 'react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, PieChart, Pie, Cell
} from 'recharts'
import {
  DollarSign, TrendingUp, TrendingDown, Activity,
  RefreshCw, Sparkles, AlertTriangle, ChevronRight
} from 'lucide-react'
import { portfolioAPI, aiAPI, tradersAPI, API_URL } from '../services/api'
import {
  Card, PageHeader, StatCard, HealthRing, PnlDisplay,
  Badge, Spinner, EmptyState, SectionHeader, RiskPill
} from '../components/common/ui'
import { usePortfolio } from '../App'

// ──────────────────────────────────────────────
// Custom chart tooltip
// ──────────────────────────────────────────────
function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-surface-800 border border-surface-700 rounded-lg p-3 shadow-xl">
      <p className="text-xs text-surface-400 mb-1 font-body">{label}</p>
      <p className="text-sm font-mono text-white">
        ${payload[0]?.value?.toLocaleString('en-US', { minimumFractionDigits: 2 })}
      </p>
      {payload[1] && (
        <p className={`text-xs font-mono mt-0.5 ${payload[1].value >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
          {payload[1].value >= 0 ? '+' : ''}${payload[1].value?.toFixed(2)} PnL
        </p>
      )}
    </div>
  )
}

// ──────────────────────────────────────────────
// Allocation pie chart
// ──────────────────────────────────────────────
const PIE_COLORS = ['#0ea5e9', '#10b981', '#f59e0b', '#8b5cf6', '#ef4444', '#06b6d4']

function AllocationChart({ traders }) {
  if (!traders?.length) return (
    <div className="h-40 flex items-center justify-center">
      <p className="text-sm text-surface-500">No traders found</p>
    </div>
  )

  const data = traders.map(t => ({
    name: t.trader_username,
    value: t.allocation_pct,
  }))

  return (
    <div className="flex items-center gap-6">
      <ResponsiveContainer width={120} height={120}>
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            innerRadius={35}
            outerRadius={55}
            paddingAngle={3}
            dataKey="value"
          >
            {data.map((_, i) => (
              <Cell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} stroke="transparent" />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
      <div className="flex-1 space-y-2">
        {data.map((d, i) => (
          <div key={i} className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full" style={{ backgroundColor: PIE_COLORS[i % PIE_COLORS.length] }} />
              <span className="text-xs text-surface-300 font-body truncate max-w-[100px]">{d.name}</span>
            </div>
            <span className="text-xs font-mono text-surface-200">{d.value.toFixed(1)}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────
// AI Recommendation card
// ──────────────────────────────────────────────
function AIRecommendationCard({ rec }) {
  const confidenceColor = {
    high: 'text-emerald-400', medium: 'text-amber-400', low: 'text-surface-400'
  }[rec.confidence] || 'text-surface-400'

  const riskBadge = { low: 'green', medium: 'yellow', high: 'red' }[rec.risk_level] || 'gray'

  return (
    <div className="border border-surface-700 rounded-lg p-4 hover:border-surface-600 transition-colors">
      <div className="flex items-start justify-between gap-3 mb-2">
        <p className="text-sm font-medium text-white font-body">{rec.title}</p>
        <Badge variant={riskBadge}>{rec.risk_level} risk</Badge>
      </div>
      <p className="text-xs text-surface-400 font-body leading-relaxed">{rec.summary}</p>
      <p className={`text-xs mt-2 font-body ${confidenceColor}`}>
        Confidence: {rec.confidence}
      </p>
    </div>
  )
}

// ──────────────────────────────────────────────
// Main Dashboard
// ──────────────────────────────────────────────
export default function Dashboard() {
  const { portfolioId } = usePortfolio()
  const [portfolio, setPortfolio]       = useState(null)
  const [health, setHealth]             = useState(null)
  const [perfData, setPerfData]         = useState([])
  const [traders, setTraders]           = useState([])
  const [recs, setRecs]                 = useState([])
  const [loading, setLoading]           = useState(true)
  const [aiLoading, setAiLoading]       = useState(false)
  const [error, setError]               = useState(null)

  const fetchData = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [p, h, perf, t, r] = await Promise.all([
        portfolioAPI.get(portfolioId),
        portfolioAPI.health(portfolioId),
        portfolioAPI.performance(portfolioId, 30),
        tradersAPI.list(portfolioId),
        aiAPI.recommendations(portfolioId, 3),
      ])
      setPortfolio(p)
      setHealth(h)
      setPerfData(perf)
      setTraders(t)
      setRecs(r)
    } catch (e) {
      setError('Failed to load portfolio data. Ensure the backend is running.')
    } finally {
      setLoading(false)
    }
  }, [portfolioId])

  useEffect(() => { fetchData() }, [fetchData])

  const runAIAnalysis = async () => {
    setAiLoading(true)
    try {
      await aiAPI.analyze({ portfolio_id: portfolioId, analysis_type: 'general' })
      const r = await aiAPI.recommendations(portfolioId, 3)
      setRecs(r)
    } catch (e) {
      console.error('AI analysis failed:', e)
    } finally {
      setAiLoading(false)
    }
  }

  const syncEToroData = async () => {
    setLoading(true)
    try {
      const response = await fetch(`${API_URL}/api/portfolios/${portfolioId}/sync`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
      if (response.ok) {
        const data = await response.json()
        console.log('Sync successful:', data)
        // Refresh portfolio data after sync
        await fetchData()
      } else {
        console.error('Sync failed:', await response.json())
        setError('Failed to sync eToro data. Check your API credentials.')
      }
    } catch (e) {
      console.error('Sync error:', e)
      setError('Network error while syncing eToro data.')
    } finally {
      setLoading(false)
    }
  }

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <div className="text-center">
        <Spinner size="lg" />
        <p className="text-surface-400 text-sm mt-3 font-body">Loading portfolio…</p>
      </div>
    </div>
  )

  if (error) return (
    <div className="flex items-center justify-center h-64">
      <div className="text-center max-w-sm">
        <AlertTriangle size={28} className="text-amber-400 mx-auto mb-3" />
        <p className="text-white font-body font-medium mb-1">Connection Error</p>
        <p className="text-surface-400 text-sm font-body">{error}</p>
        <button onClick={fetchData} className="mt-4 px-4 py-2 bg-brand-500 text-white rounded-lg text-sm hover:bg-brand-600 transition-colors">
          Retry
        </button>
      </div>
    </div>
  )

  const p = portfolio || {}
  const h = health || {}

  return (
    <div className="space-y-6">
      <PageHeader
        title="Portfolio Dashboard"
        subtitle={`Last updated ${p.last_updated ? new Date(p.last_updated).toLocaleTimeString() : '—'}`}
        actions={
          <div className="flex items-center gap-2">
            <button
              onClick={syncEToroData}
              className="flex items-center gap-2 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 border border-emerald-500 rounded-lg text-xs text-white transition-colors font-medium"
              title="Sync live data from eToro"
            >
              <Sparkles size={13} />
              Sync eToro
            </button>
            <button
              onClick={fetchData}
              className="flex items-center gap-2 px-3 py-1.5 bg-surface-800 hover:bg-surface-700 border border-surface-700 rounded-lg text-xs text-surface-300 transition-colors"
            >
              <RefreshCw size={13} />
              Refresh
            </button>
          </div>
        }
      />

      {/* Stat Cards Row */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Total Value"
          value={`$${(p.total_value || 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}`}
          icon={DollarSign}
          colorClass="bg-brand-500/15"
        />
        <StatCard
          label="Daily PnL"
          value={<PnlDisplay value={p.daily_pnl || 0} />}
          subvalue={`${p.daily_pnl >= 0 ? '+' : ''}${((p.daily_pnl || 0) / (p.total_value || 1) * 100).toFixed(2)}%`}
          trend={p.daily_pnl || 0}
          icon={p.daily_pnl >= 0 ? TrendingUp : TrendingDown}
          colorClass={p.daily_pnl >= 0 ? 'bg-emerald-500/15' : 'bg-red-500/15'}
        />
        <StatCard
          label="Monthly PnL"
          value={<PnlDisplay value={p.monthly_pnl || 0} />}
          subvalue={`${p.monthly_pnl >= 0 ? '+' : ''}${((p.monthly_pnl || 0) / (p.total_value || 1) * 100).toFixed(2)}%`}
          trend={p.monthly_pnl || 0}
          icon={Activity}
          colorClass="bg-purple-500/15"
        />
        <Card className="flex items-center justify-between">
          <div>
            <p className="text-xs text-surface-400 uppercase tracking-wider font-body">Health Score</p>
            <p className="font-display text-xl text-white mt-1">{(p.health_score || 0).toFixed(1)}</p>
            <p className="text-xs text-surface-400 font-body mt-0.5">
              Risk: <span className={`font-medium ${
                h.risk_exposure === 'critical' ? 'text-red-400' :
                h.risk_exposure === 'high' ? 'text-amber-400' :
                h.risk_exposure === 'medium' ? 'text-yellow-400' : 'text-emerald-400'
              }`}>{(h.risk_exposure || 'low').toUpperCase()}</span>
            </p>
          </div>
          <HealthRing score={p.health_score || 0} size={72} />
        </Card>
      </div>

      {/* Growth Chart + Allocation */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Card className="lg:col-span-2">
          <SectionHeader title="Portfolio Growth — 30 Days" />
          {perfData.length > 0 ? (
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={perfData} margin={{ top: 5, right: 5, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="valueGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="#0ea5e9" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#0ea5e9" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 11 }} tickLine={false} />
                <YAxis tick={{ fill: '#64748b', fontSize: 11 }} tickLine={false} axisLine={false}
                  tickFormatter={v => `$${(v/1000).toFixed(1)}k`} />
                <Tooltip content={<ChartTooltip />} />
                <Area type="monotone" dataKey="value" stroke="#0ea5e9" strokeWidth={2}
                  fill="url(#valueGrad)" dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <EmptyState title="No performance data yet" description="Data will appear after daily snapshots are recorded." />
          )}
        </Card>

        <Card>
          <SectionHeader title="Allocation by Trader" />
          <AllocationChart traders={traders} />
        </Card>
      </div>

      {/* PnL breakdown + Traders summary */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* PnL Breakdown */}
        <Card>
          <SectionHeader title="PnL Breakdown" />
          <div className="space-y-3">
            {[
              { label: 'Unrealized PnL', value: p.unrealized_pnl || 0 },
              { label: 'Realized PnL',   value: p.realized_pnl   || 0 },
              { label: 'Weekly PnL',     value: p.weekly_pnl     || 0 },
              { label: 'Monthly PnL',    value: p.monthly_pnl    || 0 },
            ].map(({ label, value }) => (
              <div key={label} className="flex items-center justify-between py-2 border-b border-surface-800 last:border-0">
                <span className="text-sm text-surface-400 font-body">{label}</span>
                <PnlDisplay value={value} className="text-sm" />
              </div>
            ))}
          </div>
          <div className="mt-3 pt-3 border-t border-surface-700">
            <div className="flex justify-between">
              <span className="text-sm font-medium text-white font-body">Invested Amount</span>
              <span className="font-mono text-sm text-surface-200">
                ${(p.invested_amount || 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}
              </span>
            </div>
          </div>
        </Card>

        {/* Traders overview */}
        <Card>
          <SectionHeader
            title="Copied Traders"
            action={
              <a href="/traders" className="text-xs text-brand-400 hover:text-brand-300 flex items-center gap-1">
                View all <ChevronRight size={12} />
              </a>
            }
          />
          {traders.length === 0 ? (
            <EmptyState title="No traders copied yet" />
          ) : (
            <div className="space-y-3">
              {traders.slice(0, 4).map(t => (
                <div key={t.id} className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="w-8 h-8 rounded-full bg-surface-700 flex items-center justify-center shrink-0">
                      <span className="text-xs font-mono text-surface-300">
                        {t.trader_username.slice(0, 2).toUpperCase()}
                      </span>
                    </div>
                    <div className="min-w-0">
                      <p className="text-sm text-white font-body truncate">{t.trader_username}</p>
                      <RiskPill level={t.risk_classification} />
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <PnlDisplay value={t.total_return_pct} prefix="" className="text-sm" />
                    <p className="text-xs text-surface-500 font-body">%</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {/* AI Recommendations */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <SectionHeader title="AI Recommendations" />
          <button
            onClick={runAIAnalysis}
            disabled={aiLoading}
            className="flex items-center gap-2 px-3 py-1.5 bg-brand-500/15 hover:bg-brand-500/25 border border-brand-500/20 rounded-lg text-xs text-brand-400 transition-colors disabled:opacity-50"
          >
            {aiLoading ? <Spinner size="sm" /> : <Sparkles size={13} />}
            {aiLoading ? 'Analyzing…' : 'Run Analysis'}
          </button>
        </div>
        {recs.length === 0 ? (
          <EmptyState
            icon={Sparkles}
            title="No recommendations yet"
            description="Click 'Run Analysis' to get AI-powered insights about your portfolio."
          />
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
            {recs.map(r => <AIRecommendationCard key={r.id} rec={r} />)}
          </div>
        )}
      </Card>
    </div>
  )
}
