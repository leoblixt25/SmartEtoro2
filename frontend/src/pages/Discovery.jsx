import React, { useState, useEffect, useCallback, useRef } from 'react'
import { Search, RefreshCw, TrendingUp, TrendingDown, DollarSign, Play, RotateCcw } from 'lucide-react'
import { API_URL, screenerAPI } from '../services/api'
import { Card, PageHeader, Spinner, EmptyState } from '../components/common/ui'
import { usePortfolio } from '../App'

const SCAN_PRESETS = [
  { label: '500 (fast)', value: 500, time: '~10 sec' },
  { label: '2,000 (balanced)', value: 2000, time: '~30 sec' },
  { label: '5,000 (deep)', value: 5000, time: '~1\u20132 min' },
  { label: '10,000 (full)', value: 10000, time: '~3\u20135 min' },
]

export default function Discovery() {
  const { portfolioId } = usePortfolio()
  const [scanLevel, setScanLevel] = useState(2000)
  const [running, setRunning] = useState(false)
  const [runId, setRunId] = useState(null)
  const [progress, setProgress] = useState(null)
  const [results, setResults] = useState(null)
  const [error, setError] = useState(null)
  const pollRef = useRef(null)

  const preset = SCAN_PRESETS.find(p => p.value === scanLevel) || SCAN_PRESETS[1]

  // Poll for progress
  useEffect(() => {
    if (!runId || !running) return
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

  const runScan = useCallback(async () => {
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
      setError(e?.response?.data?.detail || e.message || 'Failed')
    }
  }, [portfolioId, scanLevel])

  const stageLine = progress ? (
    progress.stage_name === 'Complete' ? (
      <div className="flex items-center gap-2 text-sm">
        <span className="text-emerald-400 font-medium">Done</span>
        <span className="text-surface-400 text-xs">{progress.detail}</span>
      </div>
    ) : progress.stage_name === 'Error' ? (
      <div className="text-sm text-red-400">{progress.detail}</div>
    ) : (
      <div className="space-y-2">
        <div className="flex items-center gap-2 text-sm">
          <span className="text-surface-200 font-medium">{progress.stage_name}</span>
          <span className="text-surface-500 text-xs ml-auto">{progress.pct.toFixed(0)}%</span>
        </div>
        <div className="w-full bg-surface-800 rounded-full h-1">
          <div className="bg-brand-500 h-1 rounded-full transition-all duration-500" style={{ width: `${Math.min(progress.pct, 100)}%` }} />
        </div>
        <p className="text-xs text-surface-500">{progress.detail}</p>
      </div>
    )
  ) : null

  return (
    <div className="space-y-6">
      <PageHeader
        title="Discovery"
        subtitle="Scan thousands of eToro traders in 5 stages"
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <Card>
          <p className="text-xs text-surface-400 uppercase tracking-wider">Scan Level</p>
          <select
            value={scanLevel}
            onChange={e => setScanLevel(Number(e.target.value))}
            className="mt-2 w-full bg-surface-800 border border-surface-700 text-white text-sm rounded-lg px-3 py-2 focus:outline-none focus:ring-1 focus:ring-brand-500 appearance-none cursor-pointer"
          >
            {SCAN_PRESETS.map(p => (
              <option key={p.value} value={p.value}>{p.label}</option>
            ))}
          </select>
          <p className="text-xs text-surface-500 mt-1">Est: {preset.time}</p>
        </Card>
        <Card>
          <p className="text-xs text-surface-400 uppercase tracking-wider">Discovered</p>
          <p className="font-display text-2xl mt-1 text-white">{progress?.discovered || results?.progress?.stats?.discovered || 0}</p>
        </Card>
        <Card>
          <p className="text-xs text-surface-400 uppercase tracking-wider">After Filter</p>
          <p className="font-display text-2xl mt-1 text-amber-400">{progress?.after_filter || results?.progress?.stats?.after_filter || 0}</p>
        </Card>
        <Card>
          <p className="text-xs text-surface-400 uppercase tracking-wider">Finalists</p>
          <p className="font-display text-2xl mt-1 text-emerald-400">{progress?.final_count || results?.progress?.stats?.final_count || 0}</p>
        </Card>
      </div>

      {!running && !results && (
        <div className="flex items-center gap-3">
          <button
            onClick={runScan}
            className="flex items-center gap-2 px-5 py-2.5 bg-brand-500 text-white text-sm font-medium rounded-lg hover:bg-brand-600 transition-colors"
          >
            <Play size={14} fill="currentColor" /> Run screener
          </button>
        </div>
      )}

      {running && progress && (
        <Card>
          {stageLine}
        </Card>
      )}

      {error && (
        <Card className="border-red-500/30">
          <p className="text-sm text-red-400">{error}</p>
        </Card>
      )}

      {results && results.results?.length > 0 && (
        <div className="space-y-3">
          <p className="text-sm text-surface-400">
            {results.results.length} finalists from {results.stats?.discovered || 0} scanned
            {results.stats?.duration_seconds ? ` in ${results.stats.duration_seconds}s` : ''}
          </p>
          {results.results.map((t, i) => {
            const ret = t.total_return_pct
            const score = t.final_score ?? t.score ?? 0
            return (
              <Card key={t.username}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <span className="text-xs font-mono text-surface-500 w-5">{i + 1}.</span>
                    <div>
                      <p className="text-sm font-semibold text-white">{t.username}</p>
                      <p className="text-xs text-surface-400">
                        Score: {score.toFixed(0)}/100  |  Return: {ret != null ? `${ret >= 0 ? '+' : ''}${ret.toFixed(1)}%` : 'N/A'}  |  Risk: {t.risk_score != null ? `${t.risk_score.toFixed(1)}/10` : 'N/A'}
                      </p>
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <p className="text-xs text-surface-400">Min Copy</p>
                    <p className="text-sm font-mono text-surface-200">${t.min_copy_amount?.toFixed(0) || '200'}</p>
                  </div>
                </div>
              </Card>
            )
          })}
        </div>
      )}

      {results && results.results?.length === 0 && !running && (
        <EmptyState icon={Search} title="No traders found" description="Try a larger scan level or adjust filters." />
      )}
    </div>
  )
}
