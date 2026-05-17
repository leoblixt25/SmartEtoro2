import React, { useState, useCallback } from 'react'
import { ChevronDown, RotateCcw, Play } from 'lucide-react'
import { portfolioAPI } from '../services/api'
import { usePortfolio } from '../App'

const DEFAULT_WEIGHTS = {
  consistency: 25,
  drawdown: 25,
  return: 20,
  riskScore: 20,
  winRatio: 5,
  trend: 5,
}

const DEFAULT_FILTERS = {
  period: '3m',
  maxRisk: '',
  minWeeks: '',
  minGain: '',
  maxGain: '',
  results: '10',
}

const PERIOD_OPTIONS = ['1w', '1m', '3m', '6m', '1y', 'All']
const RESULTS_OPTIONS = ['5', '10', '20', '50', '100']

function SliderRow({ label, value, onChange }) {
  const pct = (value / 100) * 100

  const handleChange = (e) => {
    onChange(Number(e.target.value))
  }

  return (
    <div className="flex items-center gap-3 group">
      <label className="text-[11px] text-gray-500 w-32 shrink-0 leading-snug tracking-wide">{label}</label>
      <div className="relative flex-1 h-5 flex items-center">
        <input
          type="range"
          min={0}
          max={100}
          value={value}
          onChange={handleChange}
          className="screener-slider"
          style={{ '--pct': `${pct}%` }}
        />
      </div>
      <span className="text-xs font-mono text-gray-700 w-8 text-right tabular-nums font-medium">{value}</span>
    </div>
  )
}

function FormField({ label, type, value, onChange, options, min, max, placeholder }) {
  const id = label.replace(/\s+/g, '-').toLowerCase()

  if (type === 'select') {
    return (
      <div>
        <label htmlFor={id} className="block text-[11px] text-gray-500 mb-1.5 tracking-wide">{label}</label>
        <select
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full px-3 py-2.5 bg-white border border-gray-200 rounded-lg text-sm text-gray-700 focus:outline-none focus:ring-1 focus:ring-gray-400 focus:border-gray-400 appearance-none cursor-pointer"
        >
          {options.map((opt) => (
            <option key={opt} value={opt}>{opt}</option>
          ))}
        </select>
      </div>
    )
  }

  return (
    <div>
      <label htmlFor={id} className="block text-[11px] text-gray-500 mb-1.5 tracking-wide">{label}</label>
      <input
        id={id}
        type="number"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        min={min}
        max={max}
        placeholder={placeholder || ''}
        className="w-full px-3 py-2.5 bg-white border border-gray-200 rounded-lg text-sm text-gray-700 focus:outline-none focus:ring-1 focus:ring-gray-400 focus:border-gray-400 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
      />
    </div>
  )
}

export default function Overview() {
  const { portfolioId } = usePortfolio()
  const [weights, setWeights] = useState(DEFAULT_WEIGHTS)
  const [filters, setFilters] = useState(DEFAULT_FILTERS)
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const totalWeight = Object.values(weights).reduce((a, b) => a + b, 0)

  const updateWeight = (key) => (val) => {
    setWeights((prev) => ({ ...prev, [key]: val }))
  }

  const updateFilter = (key) => (val) => {
    setFilters((prev) => ({ ...prev, [key]: val }))
  }

  const runScreener = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await portfolioAPI.discovery(portfolioId)
      const eligible = data?.eligible || []

      const filtered = eligible.filter((t) => {
        if (filters.maxRisk && (t.risk_score || 0) > Number(filters.maxRisk)) return false
        if (filters.minWeeks && (t.weeks_since_registration || 0) < Number(filters.minWeeks)) return false
        if (filters.minGain && (t.total_return_pct || 0) < Number(filters.minGain)) return false
        if (filters.maxGain && (t.total_return_pct || 0) > Number(filters.maxGain)) return false
        return true
      })

      const limit = Number(filters.results) || 10
      const top = filtered.slice(0, limit)

      setResults({
        traders: top,
        totalScanned: data?.stats?.total_scanned || 0,
        totalEligible: eligible.length,
        passedFilters: top.length,
      })
    } catch (e) {
      setError(e?.response?.data?.detail || e.message || 'Failed to run screener')
    } finally {
      setLoading(false)
    }
  }, [portfolioId, filters])

  const clearAll = () => {
    setWeights(DEFAULT_WEIGHTS)
    setFilters(DEFAULT_FILTERS)
    setResults(null)
    setError(null)
  }

  return (
    <>
      <style>{`
        .screener-slider {
          -webkit-appearance: none;
          appearance: none;
          width: 100%;
          height: 4px;
          border-radius: 999px;
          background: linear-gradient(to right, #111827 var(--pct, 0%), #e5e7eb var(--pct, 0%));
          outline: none;
          cursor: pointer;
          transition: background 0.1s;
        }
        .screener-slider::-webkit-slider-thumb {
          -webkit-appearance: none;
          appearance: none;
          width: 16px;
          height: 16px;
          border-radius: 999px;
          background: white;
          border: 1px solid #d1d5db;
          box-shadow: 0 1px 3px rgba(0,0,0,0.08);
          cursor: pointer;
          transition: box-shadow 0.15s, transform 0.15s;
        }
        .screener-slider::-webkit-slider-thumb:hover {
          box-shadow: 0 2px 8px rgba(0,0,0,0.12);
          transform: scale(1.1);
        }
        .screener-slider::-moz-range-thumb {
          width: 16px;
          height: 16px;
          border-radius: 999px;
          background: white;
          border: 1px solid #d1d5db;
          box-shadow: 0 1px 3px rgba(0,0,0,0.08);
          cursor: pointer;
        }
        .screener-slider:active::-webkit-slider-thumb {
          transform: scale(1.15);
        }
      `}</style>

      <div className="min-h-screen bg-gray-50 -m-4 lg:-m-6 p-6 lg:p-8">
        <div className="max-w-xl mx-auto space-y-6">

          {/* ─── HEADER ─── */}
          <div className="text-center">
            <h1 className="text-lg font-semibold text-gray-900 tracking-tight">Trader Screener</h1>
            <p className="text-xs text-gray-400 mt-1">Rank and filter eToro traders by custom criteria</p>
          </div>

          {/* ─── SCORING WEIGHTS ─── */}
          <div className="bg-white rounded-2xl border border-gray-100 shadow-[0_1px_6px_-2px_rgba(0,0,0,0.08)] p-6">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-[10px] font-semibold tracking-[0.15em] text-gray-900 uppercase">Scoring Weights</h2>
              <span className="text-[11px] font-mono font-medium text-gray-400 bg-gray-100 px-2.5 py-0.5 rounded-full">{totalWeight}%</span>
            </div>
            <div className="space-y-4">
              <SliderRow label="Consistency (prof. weeks)" value={weights.consistency} onChange={updateWeight('consistency')} />
              <SliderRow label="Drawdown protection" value={weights.drawdown} onChange={updateWeight('drawdown')} />
              <SliderRow label="Return (gain)" value={weights.return} onChange={updateWeight('return')} />
              <SliderRow label="Risk score (low=good)" value={weights.riskScore} onChange={updateWeight('riskScore')} />
              <SliderRow label="Win ratio" value={weights.winRatio} onChange={updateWeight('winRatio')} />
              <SliderRow label="Trend (this week)" value={weights.trend} onChange={updateWeight('trend')} />
            </div>
          </div>

          {/* ─── FILTERS ─── */}
          <div className="bg-white rounded-2xl border border-gray-100 shadow-[0_1px_6px_-2px_rgba(0,0,0,0.08)] p-6">
            <h2 className="text-[10px] font-semibold tracking-[0.15em] text-gray-900 uppercase mb-6">Filters</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-5 gap-y-4">
              <FormField label="Period" type="select" options={PERIOD_OPTIONS} value={filters.period} onChange={updateFilter('period')} />
              <FormField label="Max risk score (1-10)" type="number" min={1} max={10} value={filters.maxRisk} onChange={updateFilter('maxRisk')} />
              <FormField label="Min weeks registered" type="number" min={0} value={filters.minWeeks} onChange={updateFilter('minWeeks')} />
              <FormField label="Min gain (%)" type="number" value={filters.minGain} onChange={updateFilter('minGain')} placeholder="e.g. 10" />
              <FormField label="Max gain (%)" type="number" value={filters.maxGain} onChange={updateFilter('maxGain')} placeholder="e.g. 500" />
              <FormField label="Results to fetch" type="select" options={RESULTS_OPTIONS} value={filters.results} onChange={updateFilter('results')} />
            </div>
          </div>

          {/* ─── BUTTONS ─── */}
          <div className="flex items-center gap-3">
            <button
              onClick={runScreener}
              disabled={loading}
              className="flex-1 flex items-center justify-center gap-2 px-5 py-2.5 bg-gray-900 text-white text-sm font-medium rounded-xl hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {loading ? (
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : (
                <Play size={14} fill="currentColor" />
              )}
              Run screener
            </button>
            <button
              onClick={clearAll}
              className="flex items-center justify-center gap-1.5 px-4 py-2.5 bg-white border border-gray-200 text-gray-500 text-sm font-medium rounded-xl hover:bg-gray-50 hover:text-gray-700 transition-colors"
            >
              <RotateCcw size={13} />
              Clear
            </button>
          </div>

          {/* ─── SCROLL TO RESULTS ─── */}
          {results && results.traders.length > 0 && (
            <div className="flex justify-center">
              <button
                onClick={() => document.getElementById('screener-results')?.scrollIntoView({ behavior: 'smooth' })}
                className="w-9 h-9 flex items-center justify-center bg-white border border-gray-200 rounded-full shadow-sm text-gray-400 hover:text-gray-600 hover:shadow-md transition-all"
              >
                <ChevronDown size={16} />
              </button>
            </div>
          )}

          {/* ─── RESULTS ─── */}
          {results && (
            <div id="screener-results" className="bg-white rounded-2xl border border-gray-100 shadow-[0_1px_6px_-2px_rgba(0,0,0,0.08)] p-6">
              <div className="flex items-center justify-between mb-5">
                <h2 className="text-[10px] font-semibold tracking-[0.15em] text-gray-900 uppercase">Results</h2>
                <span className="text-[11px] text-gray-400">
                  {results.passedFilters} of {results.totalEligible} eligible
                </span>
              </div>

              {results.traders.length === 0 ? (
                <div className="text-center py-10">
                  <p className="text-sm text-gray-400">No traders match the selected filters.</p>
                </div>
              ) : (
                <div className="space-y-1">
                  <div className="flex items-center text-[10px] text-gray-400 uppercase tracking-wider px-3 py-2 border-b border-gray-100">
                    <span className="w-6 shrink-0">#</span>
                    <span className="flex-1">Trader</span>
                    <span className="w-16 text-right">Score</span>
                    <span className="w-16 text-right">Return</span>
                    <span className="w-14 text-right">Risk</span>
                    <span className="w-14 text-right">DD</span>
                  </div>
                  {results.traders.map((t, i) => {
                    const ret = t.total_return_pct
                    const risk = t.risk_score
                    const dd = t.peak_to_valley || t.max_drawdown
                    const score = t.final_score ?? t.score ?? 0
                    return (
                      <div
                        key={t.username || i}
                        className="flex items-center text-xs text-gray-700 px-3 py-2.5 rounded-lg hover:bg-gray-50 transition-colors"
                      >
                        <span className="w-6 shrink-0 text-gray-400 font-mono">{i + 1}</span>
                        <span className="flex-1 font-medium text-gray-900">{t.username}</span>
                        <span className="w-16 text-right font-mono tabular-nums">{score.toFixed(0)}</span>
                        <span className={`w-16 text-right font-mono tabular-nums ${ret >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>
                          {ret != null ? `${ret >= 0 ? '+' : ''}${ret.toFixed(1)}%` : '—'}
                        </span>
                        <span className="w-14 text-right font-mono tabular-nums text-gray-500">{risk != null ? risk.toFixed(1) : '—'}</span>
                        <span className="w-14 text-right font-mono tabular-nums text-gray-500">{dd != null ? `${Math.abs(dd).toFixed(1)}%` : '—'}</span>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )}

          {/* ─── ERROR ─── */}
          {error && (
            <div className="bg-red-50 border border-red-100 rounded-xl px-4 py-3 text-xs text-red-600">
              {error}
            </div>
          )}

        </div>
      </div>
    </>
  )
}
