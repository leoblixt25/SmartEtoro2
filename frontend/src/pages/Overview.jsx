import React, { useState, useCallback, useRef, useEffect } from 'react'
import { ChevronDown, RotateCcw, Play, Search, AlertTriangle } from 'lucide-react'
import { portfolioAPI, screenerAPI } from '../services/api'
import { usePortfolio } from '../App'

const SCAN_PRESETS = [
  { label: '500 (fast)', value: 500, time: '~10 sec' },
  { label: '2,000 (balanced)', value: 2000, time: '~30 sec' },
  { label: '5,000 (deep)', value: 5000, time: '~1\u20132 min' },
  { label: '10,000 (full)', value: 10000, time: '~3\u20135 min' },
]

const PERIOD_OPTIONS = ['1w', '1m', '3m', '6m', '1y', 'All']

const STAGE_ICONS = {
  1: '\uD83D\uDD0D',
  2: '\uD83D\uDD0D',
  3: '\uD83D\uDCCA',
  4: '\uD83C\uDFC6',
  5: '\uD83C\uDFC6',
  '-1': '\u26A0\uFE0F',
}

function SliderRow({ label, value, onChange }) {
  const pct = (value / 100) * 100
  return (
    <div className="flex items-center gap-3 group">
      <label className="text-[11px] text-gray-500 w-32 shrink-0 leading-snug tracking-wide">{label}</label>
      <div className="relative flex-1 h-5 flex items-center">
        <input
          type="range"
          min={0} max={100}
          value={value}
          onChange={e => onChange(Number(e.target.value))}
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
          id={id} value={value}
          onChange={e => onChange(e.target.value)}
          className="w-full px-3 py-2.5 bg-white border border-gray-200 rounded-lg text-sm text-gray-700 focus:outline-none focus:ring-1 focus:ring-gray-400 focus:border-gray-400 appearance-none cursor-pointer"
        >
          {options.map(o => <option key={o} value={o}>{o}</option>)}
        </select>
      </div>
    )
  }
  return (
    <div>
      <label htmlFor={id} className="block text-[11px] text-gray-500 mb-1.5 tracking-wide">{label}</label>
      <input
        id={id} type="number" value={value}
        onChange={e => onChange(e.target.value)}
        min={min} max={max} placeholder={placeholder || ''}
        className="w-full px-3 py-2.5 bg-white border border-gray-200 rounded-lg text-sm text-gray-700 focus:outline-none focus:ring-1 focus:ring-gray-400 focus:border-gray-400 [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none"
      />
    </div>
  )
}

function ProgressBar({ pct }) {
  return (
    <div className="w-full bg-gray-100 rounded-full h-1.5">
      <div className="bg-gray-900 h-1.5 rounded-full transition-all duration-500 ease-out" style={{ width: `${Math.min(pct, 100)}%` }} />
    </div>
  )
}

export default function Overview() {
  const { portfolioId } = usePortfolio()
  const [weights, setWeights] = useState({ consistency: 25, drawdown: 25, return: 20, riskScore: 20, winRatio: 5, trend: 5 })
  const [filters, setFilters] = useState({ period: '3m', maxRisk: '', minWeeks: '', minGain: '', maxGain: '' })
  const [scanLevel, setScanLevel] = useState(2000)
  const [running, setRunning] = useState(false)
  const [runId, setRunId] = useState(null)
  const [progress, setProgress] = useState(null)
  const [results, setResults] = useState(null)
  const [error, setError] = useState(null)
  const pollRef = useRef(null)

  const preset = SCAN_PRESETS.find(p => p.value === scanLevel) || SCAN_PRESETS[1]
  const totalWeight = Object.values(weights).reduce((a, b) => a + b, 0)

  const updateWeight = k => v => setWeights(p => ({ ...p, [k]: v }))
  const updateFilter = k => v => setFilters(p => ({ ...p, [k]: v }))

  // Poll for progress
  useEffect(() => {
    if (!runId || running === false) return
    pollRef.current = setInterval(async () => {
      try {
        const data = await screenerAPI.status(runId)
        const p = data.progress
        setProgress(p)

        if (p.stage_name === 'Complete' || p.stage_name === 'Error') {
          clearInterval(pollRef.current)
          setRunning(false)
          if (p.results) setResults(p)
          if (p.error) setError(p.detail)
        }
      } catch {
        clearInterval(pollRef.current)
        setRunning(false)
      }
    }, 1200)
    return () => clearInterval(pollRef.current)
  }, [runId, running])

  const runScreener = useCallback(async () => {
    setRunning(true)
    setError(null)
    setResults(null)
    setProgress({ stage: 0, stage_name: 'Starting', pct: 0, detail: 'Launching...' })
    try {
      const data = await screenerAPI.start(portfolioId, scanLevel, 10)
      setRunId(data.run_id)
      setProgress(data.progress)
    } catch (e) {
      setRunning(false)
      setError(e?.response?.data?.detail || e.message || 'Failed to start screener')
    }
  }, [portfolioId, scanLevel])

  const clearAll = () => {
    setWeights({ consistency: 25, drawdown: 25, return: 20, riskScore: 20, winRatio: 5, trend: 5 })
    setFilters({ period: '3m', maxRisk: '', minWeeks: '', minGain: '', maxGain: '' })
    setScanLevel(2000)
    setResults(null)
    setError(null)
    setProgress(null)
    setRunId(null)
    setRunning(false)
    if (pollRef.current) clearInterval(pollRef.current)
  }

  const stageLine = progress ? (
    progress.stage_name === 'Complete' || progress.stage_name === 'Error' ? (
      <div className="flex items-center gap-2 text-xs">
        {progress.stage_name === 'Complete' ? (
          <span className="text-emerald-600 font-medium">Done</span>
        ) : (
          <span className="text-red-500 font-medium">Failed</span>
        )}
        <span className="text-gray-400">{progress.detail}</span>
      </div>
    ) : (
      <div className="space-y-2">
        <div className="flex items-center gap-2 text-xs">
          <span className="text-gray-700 font-medium">{STAGE_ICONS[String(progress.stage)] || ''}</span>
          <span className="text-gray-700 font-medium">{progress.stage_name}</span>
          <span className="text-gray-400 ml-auto">{progress.pct.toFixed(0)}%</span>
        </div>
        <ProgressBar pct={progress.pct} />
        <p className="text-[11px] text-gray-400">{progress.detail}</p>
      </div>
    )
  ) : null

  return (
    <>
      <style>{`
        .screener-slider {
          -webkit-appearance: none; appearance: none; width: 100%; height: 4px;
          border-radius: 999px;
          background: linear-gradient(to right, #111827 var(--pct, 0%), #e5e7eb var(--pct, 0%));
          outline: none; cursor: pointer; transition: background 0.1s;
        }
        .screener-slider::-webkit-slider-thumb {
          -webkit-appearance: none; appearance: none; width: 16px; height: 16px;
          border-radius: 999px; background: white; border: 1px solid #d1d5db;
          box-shadow: 0 1px 3px rgba(0,0,0,0.08); cursor: pointer; transition: box-shadow 0.15s, transform 0.15s;
        }
        .screener-slider::-webkit-slider-thumb:hover {
          box-shadow: 0 2px 8px rgba(0,0,0,0.12); transform: scale(1.1);
        }
        .screener-slider::-moz-range-thumb {
          width: 16px; height: 16px; border-radius: 999px; background: white;
          border: 1px solid #d1d5db; box-shadow: 0 1px 3px rgba(0,0,0,0.08); cursor: pointer;
        }
        .screener-slider:active::-webkit-slider-thumb { transform: scale(1.15); }
      `}</style>

      <div className="min-h-screen bg-gray-50 -m-4 lg:-m-6 p-6 lg:p-8">
        <div className="max-w-xl mx-auto space-y-6">
          {/* HEADER */}
          <div className="text-center">
            <h1 className="text-lg font-semibold text-gray-900 tracking-tight">Trader Screener</h1>
            <p className="text-xs text-gray-400 mt-1">Scan up to 10,000 eToro traders in 5 stages</p>
          </div>

          {/* SCORING WEIGHTS */}
          <div className="bg-white rounded-2xl border border-gray-100 shadow-[0_1px_6px_-2px_rgba(0,0,0,0.08)] p-6">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-[10px] font-semibold tracking-[0.15em] text-gray-900 uppercase">Scoring Weights</h2>
              <span className="text-[11px] font-mono font-medium text-gray-400 bg-gray-100 px-2.5 py-0.5 rounded-full">{totalWeight}%</span>
            </div>
            <div className="space-y-4">
              <SliderRow label="Consistency" value={weights.consistency} onChange={updateWeight('consistency')} />
              <SliderRow label="Drawdown protection" value={weights.drawdown} onChange={updateWeight('drawdown')} />
              <SliderRow label="Return (gain)" value={weights.return} onChange={updateWeight('return')} />
              <SliderRow label="Risk score (low=good)" value={weights.riskScore} onChange={updateWeight('riskScore')} />
              <SliderRow label="Win ratio" value={weights.winRatio} onChange={updateWeight('winRatio')} />
              <SliderRow label="Trend (this week)" value={weights.trend} onChange={updateWeight('trend')} />
            </div>
          </div>

          {/* FILTERS */}
          <div className="bg-white rounded-2xl border border-gray-100 shadow-[0_1px_6px_-2px_rgba(0,0,0,0.08)] p-6">
            <h2 className="text-[10px] font-semibold tracking-[0.15em] text-gray-900 uppercase mb-6">Filters</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-5 gap-y-4">
              <FormField label="Period" type="select" options={PERIOD_OPTIONS} value={filters.period} onChange={updateFilter('period')} />
              <FormField label="Max risk score (1-10)" type="number" min={1} max={10} value={filters.maxRisk} onChange={updateFilter('maxRisk')} />
              <FormField label="Min weeks registered" type="number" min={0} value={filters.minWeeks} onChange={updateFilter('minWeeks')} />
              <FormField label="Min gain (%)" type="number" value={filters.minGain} onChange={updateFilter('minGain')} placeholder="e.g. 10" />
              <FormField label="Max gain (%)" type="number" value={filters.maxGain} onChange={updateFilter('maxGain')} placeholder="e.g. 500" />
              <div>
                <label className="block text-[11px] text-gray-500 mb-1.5 tracking-wide">Results to scan</label>
                <select
                  value={scanLevel}
                  onChange={e => setScanLevel(Number(e.target.value))}
                  className="w-full px-3 py-2.5 bg-white border border-gray-200 rounded-lg text-sm text-gray-700 focus:outline-none focus:ring-1 focus:ring-gray-400 focus:border-gray-400 appearance-none cursor-pointer"
                >
                  {SCAN_PRESETS.map(p => (
                    <option key={p.value} value={p.value}>{p.label}</option>
                  ))}
                </select>
                <p className="text-[10px] text-gray-400 mt-1">Est: {preset.time}</p>
              </div>
            </div>
          </div>

          {/* BUTTONS */}
          <div className="flex items-center gap-3">
            <button
              onClick={runScreener}
              disabled={running}
              className="flex-1 flex items-center justify-center gap-2 px-5 py-2.5 bg-gray-900 text-white text-sm font-medium rounded-xl hover:bg-gray-800 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {running ? (
                <div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              ) : (
                <Play size={14} fill="currentColor" />
              )}
              {running ? 'Scanning...' : 'Run screener'}
            </button>
            <button
              onClick={clearAll}
              disabled={running}
              className="flex items-center justify-center gap-1.5 px-4 py-2.5 bg-white border border-gray-200 text-gray-500 text-sm font-medium rounded-xl hover:bg-gray-50 hover:text-gray-700 disabled:opacity-50 transition-colors"
            >
              <RotateCcw size={13} /> Clear
            </button>
          </div>

          {/* PROGRESS */}
          {running && progress && (
            <div className="bg-white rounded-2xl border border-gray-100 shadow-[0_1px_6px_-2px_rgba(0,0,0,0.08)] p-5">
              {stageLine}
            </div>
          )}

          {/* RESULTS */}
          {results && results.progress?.results?.length > 0 && (
            <>
              <div className="flex justify-center">
                <button
                  onClick={() => document.getElementById('screener-results')?.scrollIntoView({ behavior: 'smooth' })}
                  className="w-9 h-9 flex items-center justify-center bg-white border border-gray-200 rounded-full shadow-sm text-gray-400 hover:text-gray-600 hover:shadow-md transition-all"
                >
                  <ChevronDown size={16} />
                </button>
              </div>
              <div id="screener-results" className="bg-white rounded-2xl border border-gray-100 shadow-[0_1px_6px_-2px_rgba(0,0,0,0.08)] p-6">
                <div className="flex items-center justify-between mb-5">
                  <h2 className="text-[10px] font-semibold tracking-[0.15em] text-gray-900 uppercase">Results</h2>
                  <span className="text-[11px] text-gray-400">
                    {results.progress.stats?.final_count || results.progress.results.length} finalists from {results.progress.stats?.discovered || 0} scanned
                  </span>
                </div>
                <div className="space-y-1">
                  <div className="flex items-center text-[10px] text-gray-400 uppercase tracking-wider px-3 py-2 border-b border-gray-100">
                    <span className="w-6 shrink-0">#</span>
                    <span className="flex-1">Trader</span>
                    <span className="w-14 text-right">Score</span>
                    <span className="w-16 text-right">Return</span>
                    <span className="w-14 text-right">Risk</span>
                    <span className="w-14 text-right">DD</span>
                  </div>
                  {results.progress.results.map((t, i) => {
                    const ret = t.total_return_pct
                    const risk = t.risk_score
                    const dd = t.peak_to_valley || t.max_drawdown
                    const score = t.final_score ?? t.score ?? 0
                    return (
                      <div key={t.username || i} className="flex items-center text-xs text-gray-700 px-3 py-2.5 rounded-lg hover:bg-gray-50 transition-colors">
                        <span className="w-6 shrink-0 text-gray-400 font-mono">{i + 1}</span>
                        <span className="flex-1 font-medium text-gray-900">{t.username}</span>
                        <span className="w-14 text-right font-mono tabular-nums">{score.toFixed(0)}</span>
                        <span className={`w-16 text-right font-mono tabular-nums ${ret >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>
                          {ret != null ? `${ret >= 0 ? '+' : ''}${ret.toFixed(1)}%` : '\u2014'}
                        </span>
                        <span className="w-14 text-right font-mono tabular-nums text-gray-500">{risk != null ? risk.toFixed(1) : '\u2014'}</span>
                        <span className="w-14 text-right font-mono tabular-nums text-gray-500">{dd != null ? `${Math.abs(dd).toFixed(1)}%` : '\u2014'}</span>
                      </div>
                    )
                  })}
                </div>
              </div>
            </>
          )}

          {/* ERROR */}
          {error && (
            <div className="bg-red-50 border border-red-100 rounded-xl px-4 py-3 text-xs text-red-600 flex items-center gap-2">
              <AlertTriangle size={14} /> {error}
            </div>
          )}
        </div>
      </div>
    </>
  )
}
