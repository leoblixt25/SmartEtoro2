/**
 * Performance Page
 * Detailed PnL charts, growth curves, and period comparisons.
 */

import React, { useState, useEffect, useCallback } from 'react'
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, ReferenceLine, ComposedChart, Line
} from 'recharts'
import { BarChart3, RefreshCw, TrendingUp } from 'lucide-react'
import { portfolioAPI } from '../services/api'
import {
  Card, PageHeader, PnlDisplay, Spinner, SectionHeader, EmptyState
} from '../components/common/ui'
import { usePortfolio } from '../App'

// ──────────────────────────────────────────────
// Period selector
// ──────────────────────────────────────────────
function PeriodSelector({ value, onChange }) {
  const options = [
    { label: '7D', days: 7 },
    { label: '30D', days: 30 },
    { label: '90D', days: 90 },
  ]
  return (
    <div className="flex gap-1 p-1 bg-surface-800 rounded-lg">
      {options.map(o => (
        <button
          key={o.days}
          onClick={() => onChange(o.days)}
          className={`px-3 py-1 rounded-md text-xs font-body transition-colors ${
            value === o.days
              ? 'bg-brand-500 text-white'
              : 'text-surface-400 hover:text-white'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

// ──────────────────────────────────────────────
// Tooltips
// ──────────────────────────────────────────────
function ValueTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-surface-800 border border-surface-700 rounded-lg p-3 shadow-xl min-w-[140px]">
      <p className="text-xs text-surface-400 mb-1 font-body">{label}</p>
      {payload.map((p, i) => (
        <p key={i} className="text-sm font-mono" style={{ color: p.color }}>
          {p.name}: {p.name === 'Value' ? '$' : ''}{p.value?.toLocaleString('en-US', { minimumFractionDigits: 2 })}
        </p>
      ))}
    </div>
  )
}

// ──────────────────────────────────────────────
// Summary stat strip
// ──────────────────────────────────────────────
function SummaryStrip({ portfolio }) {
  const p = portfolio || {}
  const investedReturn = p.invested_amount
    ? ((p.total_value - p.invested_amount) / p.invested_amount * 100)
    : 0

  return (
    <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
      {[
        { label: 'Total Return',   value: `${investedReturn >= 0 ? '+' : ''}${investedReturn.toFixed(2)}%`, color: investedReturn >= 0 ? 'text-emerald-400' : 'text-red-400' },
        { label: 'Daily PnL',      value: <PnlDisplay value={p.daily_pnl || 0} className="text-lg" />,   color: '' },
        { label: 'Weekly PnL',     value: <PnlDisplay value={p.weekly_pnl || 0} className="text-lg" />,  color: '' },
        { label: 'Monthly PnL',    value: <PnlDisplay value={p.monthly_pnl || 0} className="text-lg" />, color: '' },
        { label: 'Unrealized PnL', value: <PnlDisplay value={p.unrealized_pnl || 0} className="text-lg" />, color: '' },
      ].map(({ label, value, color }) => (
        <Card key={label}>
          <p className="text-xs text-surface-400 font-body uppercase tracking-wider">{label}</p>
          <div className={`font-display text-lg mt-1 ${color}`}>{value}</div>
        </Card>
      ))}
    </div>
  )
}

// ──────────────────────────────────────────────
// Daily PnL bar chart
// ──────────────────────────────────────────────
function DailyPnlChart({ data }) {
  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={data} margin={{ top: 5, right: 5, left: -10, bottom: 5 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
        <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 10 }} tickLine={false} />
        <YAxis tick={{ fill: '#64748b', fontSize: 10 }} tickLine={false} axisLine={false}
          tickFormatter={v => `$${v}`} />
        <Tooltip content={<ValueTooltip />} />
        <ReferenceLine y={0} stroke="#334155" />
        <Bar
          dataKey="pnl"
          name="Daily PnL"
          radius={[3, 3, 0, 0]}
          fill="#0ea5e9"
          label={false}
          // Color bars green/red by value
          // recharts doesn't support conditional fill natively; use Cell
        />
      </BarChart>
    </ResponsiveContainer>
  )
}

// ──────────────────────────────────────────────
// Portfolio value area chart
// ──────────────────────────────────────────────
function GrowthChart({ data }) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <ComposedChart data={data} margin={{ top: 5, right: 5, left: 0, bottom: 5 }}>
        <defs>
          <linearGradient id="growthGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor="#0ea5e9" stopOpacity={0.3} />
            <stop offset="95%" stopColor="#0ea5e9" stopOpacity={0} />
          </linearGradient>
          <linearGradient id="healthGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="5%"  stopColor="#10b981" stopOpacity={0.15} />
            <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
        <XAxis dataKey="date" tick={{ fill: '#64748b', fontSize: 11 }} tickLine={false} />
        <YAxis
          yAxisId="value"
          tick={{ fill: '#64748b', fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          tickFormatter={v => `$${(v/1000).toFixed(1)}k`}
        />
        <YAxis
          yAxisId="health"
          orientation="right"
          tick={{ fill: '#64748b', fontSize: 11 }}
          tickLine={false}
          axisLine={false}
          domain={[0, 100]}
          tickFormatter={v => `${v}`}
        />
        <Tooltip content={<ValueTooltip />} />
        <Area
          yAxisId="value"
          type="monotone"
          dataKey="value"
          name="Value"
          stroke="#0ea5e9"
          strokeWidth={2}
          fill="url(#growthGrad)"
          dot={false}
        />
        <Line
          yAxisId="health"
          type="monotone"
          dataKey="health"
          name="Health"
          stroke="#10b981"
          strokeWidth={1.5}
          dot={false}
          strokeDasharray="4 2"
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}

// ──────────────────────────────────────────────
// Statistics table
// ──────────────────────────────────────────────
function StatsTable({ data }) {
  if (!data.length) return null

  const values = data.map(d => d.value)
  const pnls   = data.map(d => d.pnl)

  const stats = [
    { label: 'Peak Value',      value: `$${Math.max(...values).toLocaleString('en-US', { minimumFractionDigits: 2 })}` },
    { label: 'Trough Value',    value: `$${Math.min(...values).toLocaleString('en-US', { minimumFractionDigits: 2 })}` },
    { label: 'Best Day',        value: `+$${Math.max(...pnls).toFixed(2)}` },
    { label: 'Worst Day',       value: `$${Math.min(...pnls).toFixed(2)}` },
    { label: 'Positive Days',   value: `${pnls.filter(p => p > 0).length} / ${pnls.length}` },
    { label: 'Avg Daily PnL',   value: `$${(pnls.reduce((a, b) => a + b, 0) / pnls.length).toFixed(2)}` },
  ]

  return (
    <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
      {stats.map(({ label, value }) => (
        <div key={label} className="bg-surface-800 rounded-lg p-3">
          <p className="text-xs text-surface-400 font-body">{label}</p>
          <p className="font-mono text-sm text-white mt-1">{value}</p>
        </div>
      ))}
    </div>
  )
}

// ──────────────────────────────────────────────
// Main Performance page
// ──────────────────────────────────────────────
export default function Performance() {
  const { portfolioId }  = usePortfolio()
  const [portfolio,    setPortfolio]  = useState(null)
  const [perfData,     setPerfData]   = useState([])
  const [days,         setDays]       = useState(30)
  const [loading,      setLoading]    = useState(true)

  const fetchData = useCallback(async () => {
    setLoading(true)
    try {
      const [p, perf] = await Promise.all([
        portfolioAPI.get(portfolioId),
        portfolioAPI.performance(portfolioId, days),
      ])
      setPortfolio(p)
      setPerfData(perf)
    } catch (e) {
      console.error('Failed to load performance data:', e)
    } finally {
      setLoading(false)
    }
  }, [portfolioId, days])

  useEffect(() => { fetchData() }, [fetchData])

  return (
    <div className="space-y-6">
      <PageHeader
        title="Performance"
        subtitle="Historical portfolio growth and PnL analysis"
        actions={
          <div className="flex items-center gap-2">
            <PeriodSelector value={days} onChange={setDays} />
            <button onClick={fetchData} className="p-1.5 bg-surface-800 hover:bg-surface-700 border border-surface-700 rounded-lg text-surface-400 hover:text-white transition-colors">
              <RefreshCw size={14} />
            </button>
          </div>
        }
      />

      {loading ? (
        <div className="flex justify-center py-12"><Spinner size="lg" /></div>
      ) : (
        <>
          <SummaryStrip portfolio={portfolio} />

          {/* Growth chart */}
          <Card>
            <div className="flex items-center justify-between mb-4">
              <SectionHeader title={`Portfolio Growth — ${days} Days`} />
              <div className="flex items-center gap-4 text-xs text-surface-400 font-body">
                <span className="flex items-center gap-1.5">
                  <span className="w-3 h-0.5 bg-brand-500 inline-block" /> Value
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="w-3 h-0.5 bg-emerald-500 inline-block border-dashed" style={{borderStyle:'dashed'}} /> Health
                </span>
              </div>
            </div>
            {perfData.length > 0
              ? <GrowthChart data={perfData} />
              : <EmptyState icon={TrendingUp} title="No history yet" description="Growth data builds up after daily snapshots are recorded." />
            }
          </Card>

          {/* Daily PnL */}
          <Card>
            <SectionHeader title="Daily PnL" />
            {perfData.length > 0
              ? <DailyPnlChart data={perfData} />
              : <EmptyState icon={BarChart3} title="No daily PnL data yet" />
            }
          </Card>

          {/* Stats summary */}
          {perfData.length > 0 && (
            <Card>
              <SectionHeader title={`${days}-Day Statistics`} />
              <StatsTable data={perfData} />
            </Card>
          )}
        </>
      )}
    </div>
  )
}
