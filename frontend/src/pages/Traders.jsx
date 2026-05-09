/**
 * Traders Page
 * Full copied trader management: analytics, risk scores, AI summaries.
 */

import React, { useState, useEffect, useCallback } from 'react'
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid
} from 'recharts'
import {
  Users, RefreshCw, ChevronDown, ChevronUp, Sparkles,
  PauseCircle, PlayCircle, AlertTriangle, TrendingUp, TrendingDown
} from 'lucide-react'
import { tradersAPI, aiAPI } from '../services/api'
import {
  Card, PageHeader, Badge, RiskPill, PnlDisplay,
  HealthRing, Spinner, EmptyState, SectionHeader
} from '../components/common/ui'
import { usePortfolio } from '../App'

// ──────────────────────────────────────────────
// Radar chart for trader scores
// ──────────────────────────────────────────────
function TraderRadar({ trader }) {
  const data = [
    { subject: 'Consistency',     value: trader.consistency_score    || 0 },
    { subject: 'Diversification', value: trader.diversification_score || 0 },
    { subject: 'Risk Control',    value: Math.max(0, 100 - (trader.risk_score || 5) * 10) },
    { subject: 'Low Drawdown',    value: Math.max(0, 100 - (trader.max_drawdown || 0) * 3) },
    { subject: 'Sharpe',          value: Math.min(100, Math.max(0, (trader.sharpe_score || 0) * 40 + 50)) },
  ]
  return (
    <ResponsiveContainer width="100%" height={160}>
      <RadarChart data={data} margin={{ top: 5, right: 20, bottom: 5, left: 20 }}>
        <PolarGrid stroke="#1e293b" />
        <PolarAngleAxis dataKey="subject" tick={{ fill: '#64748b', fontSize: 10 }} />
        <Radar dataKey="value" stroke="#0ea5e9" fill="#0ea5e9" fillOpacity={0.2} strokeWidth={2} />
      </RadarChart>
    </ResponsiveContainer>
  )
}

// ──────────────────────────────────────────────
// Analytics detail panel
// ──────────────────────────────────────────────
function AnalyticsPanel({ analytics, trader }) {
  if (!analytics) return (
    <div className="flex items-center justify-center py-6">
      <Spinner />
    </div>
  )

  return (
    <div className="space-y-4 pt-2">
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { label: 'Avg Monthly Return', value: `${analytics.avg_monthly_return?.toFixed(2) || 0}%`, color: analytics.avg_monthly_return >= 0 ? 'text-emerald-400' : 'text-red-400' },
          { label: 'Max Drawdown',        value: `${analytics.max_drawdown?.toFixed(1) || 0}%`,       color: analytics.max_drawdown > 20 ? 'text-red-400' : 'text-amber-400' },
          { label: 'Sharpe Score',        value: (analytics.sharpe_score || 0).toFixed(2),             color: analytics.sharpe_score >= 1 ? 'text-emerald-400' : 'text-surface-300' },
          { label: 'Volatility',          value: `${analytics.volatility?.toFixed(1) || 0}%`,          color: analytics.volatility > 30 ? 'text-red-400' : 'text-surface-300' },
        ].map(({ label, value, color }) => (
          <div key={label} className="bg-surface-800 rounded-lg p-3">
            <p className="text-xs text-surface-400 font-body mb-1">{label}</p>
            <p className={`font-mono text-base font-semibold ${color}`}>{value}</p>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Strengths */}
        {analytics.strengths?.length > 0 && (
          <div>
            <p className="text-xs font-semibold text-emerald-400 uppercase tracking-wider mb-2 font-body">✓ Strengths</p>
            <ul className="space-y-1.5">
              {analytics.strengths.map((s, i) => (
                <li key={i} className="text-xs text-surface-300 font-body flex gap-2">
                  <span className="text-emerald-500 shrink-0">•</span>{s}
                </li>
              ))}
            </ul>
          </div>
        )}
        {/* Weaknesses */}
        {analytics.weaknesses?.length > 0 && (
          <div>
            <p className="text-xs font-semibold text-amber-400 uppercase tracking-wider mb-2 font-body">⚠ Weaknesses</p>
            <ul className="space-y-1.5">
              {analytics.weaknesses.map((w, i) => (
                <li key={i} className="text-xs text-surface-300 font-body flex gap-2">
                  <span className="text-amber-500 shrink-0">•</span>{w}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* Warning signs */}
      {analytics.warning_signs?.length > 0 && (
        <div className="bg-red-500/5 border border-red-500/20 rounded-lg p-3">
          <p className="text-xs font-semibold text-red-400 uppercase tracking-wider mb-2 font-body">Risk Warnings</p>
          {analytics.warning_signs.map((w, i) => (
            <p key={i} className="text-xs text-red-300 font-body">{w}</p>
          ))}
        </div>
      )}

      {/* Sustainability + Verdict */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <div className="bg-surface-800 rounded-lg p-3">
          <p className="text-xs text-surface-400 font-body mb-1">Sustainability Outlook</p>
          <p className="text-xs text-surface-200 font-body leading-relaxed">{analytics.sustainability}</p>
        </div>
        <div className="bg-brand-500/5 border border-brand-500/15 rounded-lg p-3">
          <p className="text-xs text-surface-400 font-body mb-1">Verdict</p>
          <p className="text-sm font-semibold text-brand-300 font-body">{analytics.overall_verdict}</p>
        </div>
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────
// Single trader card
// ──────────────────────────────────────────────
function TraderCard({ trader, onRefresh }) {
  const [expanded,   setExpanded]   = useState(false)
  const [analytics,  setAnalytics]  = useState(null)
  const [loading,    setLoading]    = useState(false)
  const [aiLoading,  setAiLoading]  = useState(false)
  const [aiSummary,  setAiSummary]  = useState(trader.ai_summary)
  const [paused,     setPaused]     = useState(trader.is_paused)

  const loadAnalytics = async () => {
    if (analytics) { setExpanded(e => !e); return }
    setExpanded(true)
    setLoading(true)
    try {
      const result = await tradersAPI.analyze(trader.id)
      setAnalytics(result)
    } catch (e) {
      console.error('Analytics failed:', e)
    } finally {
      setLoading(false)
    }
  }

  const runAI = async () => {
    setAiLoading(true)
    try {
      const result = await aiAPI.analyze({
        portfolio_id: trader.portfolio_id,
        analysis_type: 'trader',
        trader_id: trader.id,
      })
      const summary = result?.recommendations?.[0]?.summary
      if (summary) setAiSummary(summary)
    } catch (e) {
      console.error('AI failed:', e)
    } finally {
      setAiLoading(false)
    }
  }

  const togglePause = async () => {
    try {
      await tradersAPI.update(trader.id, {
        is_paused: !paused,
        paused_reason: paused ? null : 'Manually paused via dashboard',
      })
      setPaused(p => !p)
    } catch (e) {
      console.error('Pause toggle failed:', e)
    }
  }

  const riskColor = trader.risk_score >= 8 ? 'text-red-400'
    : trader.risk_score >= 6 ? 'text-amber-400' : 'text-emerald-400'

  return (
    <Card className="transition-all duration-200">
      {/* Header row */}
      <div className="flex items-start gap-4">
        {/* Avatar */}
        <div className="w-10 h-10 rounded-xl bg-surface-700 flex items-center justify-center shrink-0">
          <span className="text-sm font-mono font-bold text-surface-300">
            {trader.trader_username.slice(0, 2).toUpperCase()}
          </span>
        </div>

        {/* Main info */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="font-body font-semibold text-white">{trader.trader_username}</h3>
            <RiskPill level={trader.risk_classification} />
            {paused && <Badge variant="yellow">Paused</Badge>}
          </div>
          <div className="flex items-center gap-4 mt-1 flex-wrap">
            <span className="text-xs text-surface-400 font-body">
              Allocated: <span className="text-surface-200 font-mono">${trader.allocated_amount.toLocaleString()}</span>
              <span className="text-surface-500"> ({trader.allocation_pct.toFixed(1)}%)</span>
            </span>
            <span className="text-xs text-surface-400 font-body">
              Return: <PnlDisplay value={trader.total_return_pct} prefix="" className="text-xs" />%
            </span>
          </div>
        </div>

        {/* Right: risk score + controls */}
        <div className="flex items-center gap-3 shrink-0">
          <div className="text-right hidden sm:block">
            <p className="text-xs text-surface-400 font-body">Risk Score</p>
            <p className={`font-mono text-lg font-bold ${riskColor}`}>{trader.risk_score.toFixed(1)}</p>
            <p className="text-xs text-surface-500 font-body">/10</p>
          </div>
          <div className="flex flex-col gap-1">
            <button
              onClick={togglePause}
              className="p-1.5 rounded-lg text-surface-400 hover:text-white hover:bg-surface-700 transition-colors"
              title={paused ? 'Resume copying' : 'Pause copying'}
            >
              {paused ? <PlayCircle size={16} /> : <PauseCircle size={16} />}
            </button>
            <button
              onClick={loadAnalytics}
              className="p-1.5 rounded-lg text-surface-400 hover:text-white hover:bg-surface-700 transition-colors"
              title="Toggle analytics"
            >
              {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
            </button>
          </div>
        </div>
      </div>

      {/* Quick metrics row */}
      <div className="grid grid-cols-4 gap-2 mt-4 pt-4 border-t border-surface-800">
        {[
          { label: 'Drawdown', value: `${trader.max_drawdown.toFixed(1)}%` },
          { label: 'Volatility', value: `${trader.volatility.toFixed(1)}%` },
          { label: 'Consistency', value: `${trader.consistency_score.toFixed(0)}%` },
          { label: 'Sharpe', value: trader.sharpe_score.toFixed(2) },
        ].map(({ label, value }) => (
          <div key={label} className="text-center">
            <p className="text-xs text-surface-500 font-body">{label}</p>
            <p className="text-xs font-mono text-surface-200 mt-0.5">{value}</p>
          </div>
        ))}
      </div>

      {/* Expanded analytics */}
      {expanded && (
        <div className="mt-4 pt-4 border-t border-surface-800">
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs font-semibold text-surface-200 uppercase tracking-wider font-body">
              Detailed Analytics
            </p>
            <button
              onClick={runAI}
              disabled={aiLoading}
              className="flex items-center gap-1.5 px-2.5 py-1 bg-brand-500/10 hover:bg-brand-500/20 border border-brand-500/20 rounded-lg text-xs text-brand-400 transition-colors disabled:opacity-50"
            >
              {aiLoading ? <Spinner size="sm" /> : <Sparkles size={12} />}
              AI Summary
            </button>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div>
              <p className="text-xs text-surface-400 font-body mb-1">Performance Radar</p>
              <TraderRadar trader={trader} />
            </div>
            <div>
              {loading ? (
                <div className="flex items-center justify-center h-40">
                  <Spinner />
                </div>
              ) : (
                <AnalyticsPanel analytics={analytics} trader={trader} />
              )}
            </div>
          </div>

          {/* AI Summary */}
          {aiSummary && (
            <div className="mt-4 bg-brand-500/5 border border-brand-500/15 rounded-lg p-3">
              <div className="flex items-center gap-2 mb-2">
                <Sparkles size={13} className="text-brand-400" />
                <p className="text-xs font-semibold text-brand-400 font-body">AI Analysis</p>
              </div>
              <p className="text-xs text-surface-300 font-body leading-relaxed">{aiSummary}</p>
            </div>
          )}
        </div>
      )}
    </Card>
  )
}

// ──────────────────────────────────────────────
// Comparison bar chart
// ──────────────────────────────────────────────
function TraderComparisonChart({ traders }) {
  const data = traders.map(t => ({
    name: t.trader_username.length > 10 ? t.trader_username.slice(0, 10) + '…' : t.trader_username,
    return: parseFloat(t.total_return_pct.toFixed(2)),
    risk: parseFloat(t.risk_score.toFixed(1)),
  }))

  return (
    <ResponsiveContainer width="100%" height={160}>
      <BarChart data={data} margin={{ top: 5, right: 5, left: -20, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
        <XAxis dataKey="name" tick={{ fill: '#64748b', fontSize: 10 }} tickLine={false} />
        <YAxis tick={{ fill: '#64748b', fontSize: 10 }} tickLine={false} axisLine={false} />
        <Tooltip
          contentStyle={{ background: '#1e293b', border: '1px solid #334155', borderRadius: 8 }}
          labelStyle={{ color: '#94a3b8' }}
        />
        <Bar dataKey="return" fill="#0ea5e9" radius={[3, 3, 0, 0]} name="Return %" />
        <Bar dataKey="risk"   fill="#f59e0b" radius={[3, 3, 0, 0]} name="Risk Score" />
      </BarChart>
    </ResponsiveContainer>
  )
}

// ──────────────────────────────────────────────
// Main Traders page
// ──────────────────────────────────────────────
export default function Traders() {
  const { portfolioId } = usePortfolio()
  const [traders, setTraders] = useState([])
  const [loading, setLoading] = useState(true)
  const [filter,  setFilter]  = useState('all')  // all | active | paused

  const fetchTraders = useCallback(async () => {
    setLoading(true)
    try {
      const data = await tradersAPI.list(portfolioId)
      setTraders(data)
    } catch (e) {
      console.error('Failed to load traders:', e)
    } finally {
      setLoading(false)
    }
  }, [portfolioId])

  useEffect(() => { fetchTraders() }, [fetchTraders])

  const filtered = traders.filter(t => {
    if (filter === 'active') return !t.is_paused && t.is_active
    if (filter === 'paused') return t.is_paused
    return true
  })

  const avgRisk = traders.length
    ? (traders.reduce((s, t) => s + t.risk_score, 0) / traders.length).toFixed(1)
    : '—'

  return (
    <div className="space-y-6">
      <PageHeader
        title="Copied Traders"
        subtitle="Analyse, monitor, and manage your copy relationships"
        actions={
          <button onClick={fetchTraders} className="flex items-center gap-2 px-3 py-1.5 bg-surface-800 hover:bg-surface-700 border border-surface-700 rounded-lg text-xs text-surface-300 transition-colors">
            <RefreshCw size={13} /> Refresh
          </button>
        }
      />

      {/* Summary cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        {[
          { label: 'Total Traders',    value: traders.length,                                        color: 'text-white' },
          { label: 'Active',           value: traders.filter(t => !t.is_paused).length,              color: 'text-emerald-400' },
          { label: 'Paused',           value: traders.filter(t => t.is_paused).length,               color: 'text-amber-400' },
          { label: 'Avg Risk Score',   value: avgRisk + '/10',                                        color: parseFloat(avgRisk) >= 7 ? 'text-red-400' : 'text-emerald-400' },
        ].map(({ label, value, color }) => (
          <Card key={label}>
            <p className="text-xs text-surface-400 font-body uppercase tracking-wider">{label}</p>
            <p className={`font-display text-2xl mt-1 ${color}`}>{value}</p>
          </Card>
        ))}
      </div>

      {/* Comparison chart */}
      {traders.length > 1 && (
        <Card>
          <SectionHeader title="Return vs Risk Comparison" />
          <TraderComparisonChart traders={traders} />
        </Card>
      )}

      {/* Filter tabs */}
      <div className="flex gap-2">
        {['all', 'active', 'paused'].map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 rounded-lg text-xs font-body transition-colors capitalize ${
              filter === f
                ? 'bg-brand-500/20 text-brand-400 border border-brand-500/30'
                : 'text-surface-400 hover:text-white border border-surface-700 hover:border-surface-600'
            }`}
          >
            {f} {f === 'all' ? `(${traders.length})` : f === 'active' ? `(${traders.filter(t => !t.is_paused).length})` : `(${traders.filter(t => t.is_paused).length})`}
          </button>
        ))}
      </div>

      {/* Trader cards */}
      {loading ? (
        <div className="flex justify-center py-12"><Spinner size="lg" /></div>
      ) : filtered.length === 0 ? (
        <EmptyState icon={Users} title="No traders found" description="Add copied traders to start monitoring performance." />
      ) : (
        <div className="space-y-4">
          {filtered.map(t => (
            <TraderCard key={t.id} trader={t} onRefresh={fetchTraders} />
          ))}
        </div>
      )}
    </div>
  )
}
