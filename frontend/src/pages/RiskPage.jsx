/**
 * Risk Management Page
 * Active violations, risk settings editor, and emergency controls.
 */

import React, { useState, useEffect, useCallback } from 'react'
import {
  Shield, AlertTriangle, RefreshCw, Settings, StopCircle,
  CheckCircle, Info, ChevronRight
} from 'lucide-react'
import { riskAPI } from '../services/api'
import {
  Card, PageHeader, Badge, Spinner, EmptyState,
  SectionHeader, Toggle
} from '../components/common/ui'
import { usePortfolio } from '../App'

// ──────────────────────────────────────────────
// Violation card
// ──────────────────────────────────────────────
function ViolationCard({ v }) {
  const configs = {
    critical: { border: 'border-red-500/30',   bg: 'bg-red-500/5',   icon: AlertTriangle, iconColor: 'text-red-400',    badge: 'red'    },
    warning:  { border: 'border-amber-500/30', bg: 'bg-amber-500/5', icon: AlertTriangle, iconColor: 'text-amber-400',  badge: 'yellow' },
    info:     { border: 'border-brand-500/20', bg: 'bg-brand-500/5', icon: Info,          iconColor: 'text-brand-400',  badge: 'blue'   },
  }
  const cfg = configs[v.severity] || configs.info
  const Icon = cfg.icon

  return (
    <div className={`rounded-xl border p-4 ${cfg.border} ${cfg.bg}`}>
      <div className="flex items-start gap-3">
        <Icon size={18} className={`${cfg.iconColor} shrink-0 mt-0.5`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <p className="text-sm font-semibold text-white font-body">{v.title}</p>
            <Badge variant={cfg.badge}>{v.severity}</Badge>
            {v.requires_immediate_action && (
              <Badge variant="red">Immediate Action</Badge>
            )}
          </div>
          <p className="text-xs text-surface-300 font-body leading-relaxed">{v.message}</p>
          {v.suggested_action && (
            <p className="text-xs text-surface-400 font-body mt-2 flex items-start gap-1">
              <ChevronRight size={12} className="shrink-0 mt-0.5" />
              {v.suggested_action}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────
// Risk settings editor
// ──────────────────────────────────────────────
function RiskSettingsEditor({ settings, onSave }) {
  const [form, setForm] = useState(settings || {})
  const [saving, setSaving] = useState(false)
  const [saved,  setSaved]  = useState(false)

  useEffect(() => { if (settings) setForm(settings) }, [settings])

  const handleChange = (key, value) => setForm(f => ({ ...f, [key]: value }))

  const handleSave = async () => {
    setSaving(true)
    try {
      await onSave(form)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e) {
      console.error('Save failed:', e)
    } finally {
      setSaving(false)
    }
  }

  const fields = [
    {
      key: 'max_portfolio_drawdown_pct',
      label: 'Max Portfolio Drawdown',
      unit: '%',
      min: 1, max: 50, step: 1,
      help: 'Alert when portfolio drawdown exceeds this percentage.',
    },
    {
      key: 'max_allocation_per_trader_pct',
      label: 'Max Allocation per Trader',
      unit: '%',
      min: 5, max: 80, step: 5,
      help: 'Maximum percentage of portfolio in any single copied trader.',
    },
    {
      key: 'min_traders_for_diversification',
      label: 'Min Traders (Diversification)',
      unit: 'traders',
      min: 1, max: 20, step: 1,
      help: 'Minimum number of copied traders for healthy diversification.',
    },
    {
      key: 'volatility_reduction_threshold',
      label: 'Volatility Alert Threshold',
      unit: '%',
      min: 5, max: 50, step: 5,
      help: 'Alert when a trader\'s volatility exceeds this level.',
    },
    {
      key: 'cooldown_after_loss_hours',
      label: 'Loss Cooldown Period',
      unit: 'hours',
      min: 0, max: 720, step: 12,
      help: 'Hours to wait before resuming automation after a loss event.',
    },
    {
      key: 'emergency_drawdown_trigger_pct',
      label: 'Emergency Stop Drawdown',
      unit: '%',
      min: 5, max: 40, step: 1,
      help: 'Automatically trigger emergency stop at this drawdown level.',
    },
  ]

  return (
    <Card>
      <SectionHeader title="Risk Settings" />
      <div className="space-y-4">
        {fields.map(f => (
          <div key={f.key}>
            <div className="flex items-center justify-between mb-1">
              <label className="text-sm text-surface-200 font-body">{f.label}</label>
              <span className="font-mono text-sm text-brand-400 font-semibold">
                {form[f.key]} {f.unit}
              </span>
            </div>
            <input
              type="range"
              min={f.min} max={f.max} step={f.step}
              value={form[f.key] || f.min}
              onChange={e => handleChange(f.key, parseFloat(e.target.value))}
              className="w-full h-1.5 bg-surface-700 rounded-full appearance-none cursor-pointer accent-brand-500"
            />
            <p className="text-xs text-surface-500 font-body mt-1">{f.help}</p>
          </div>
        ))}

        {/* Emergency protection toggle */}
        <div className="flex items-center justify-between py-3 border-t border-surface-800">
          <div>
            <p className="text-sm text-surface-200 font-body">Emergency Protection</p>
            <p className="text-xs text-surface-500 font-body mt-0.5">
              Automatically pause all automation at emergency drawdown threshold.
            </p>
          </div>
          <Toggle
            checked={form.emergency_protection_enabled ?? true}
            onChange={v => handleChange('emergency_protection_enabled', v)}
          />
        </div>

        <button
          onClick={handleSave}
          disabled={saving}
          className={`w-full py-2.5 rounded-lg text-sm font-body font-medium transition-colors flex items-center justify-center gap-2 ${
            saved
              ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30'
              : 'bg-brand-500 hover:bg-brand-600 text-white'
          }`}
        >
          {saving ? <Spinner size="sm" /> : saved ? <><CheckCircle size={14} /> Saved</> : 'Save Settings'}
        </button>
      </div>
    </Card>
  )
}

// ──────────────────────────────────────────────
// Main Risk page
// ──────────────────────────────────────────────
export default function RiskPage() {
  const { portfolioId } = usePortfolio()
  const [violations, setViolations] = useState([])
  const [settings,   setSettings]   = useState(null)
  const [loading,    setLoading]    = useState(true)
  const [checking,   setChecking]   = useState(false)

  const fetchAll = useCallback(async () => {
    setLoading(true)
    try {
      const [risk, s] = await Promise.all([
        riskAPI.check(portfolioId),
        riskAPI.getSettings(portfolioId),
      ])
      setViolations(risk.violations || [])
      setSettings(s)
    } catch (e) {
      console.error('Risk data load failed:', e)
    } finally {
      setLoading(false)
    }
  }, [portfolioId])

  useEffect(() => { fetchAll() }, [fetchAll])

  const runCheck = async () => {
    setChecking(true)
    try {
      const result = await riskAPI.check(portfolioId)
      setViolations(result.violations || [])
    } catch (e) {
      console.error('Risk check failed:', e)
    } finally {
      setChecking(false)
    }
  }

  const saveSettings = async (form) => {
    const updated = await riskAPI.updateSettings(portfolioId, form)
    setSettings(updated)
  }

  const criticalCount = violations.filter(v => v.severity === 'critical').length
  const warningCount  = violations.filter(v => v.severity === 'warning').length
  const infoCount     = violations.filter(v => v.severity === 'info').length

  return (
    <div className="space-y-6">
      <PageHeader
        title="Risk Management"
        subtitle="Active violations, thresholds, and emergency controls"
        actions={
          <button
            onClick={runCheck}
            disabled={checking}
            className="flex items-center gap-2 px-3 py-1.5 bg-surface-800 hover:bg-surface-700 border border-surface-700 rounded-lg text-xs text-surface-300 transition-colors"
          >
            {checking ? <Spinner size="sm" /> : <RefreshCw size={13} />}
            Run Check
          </button>
        }
      />

      {/* Summary strip */}
      <div className="grid grid-cols-3 gap-4">
        <Card className="border-red-500/20">
          <p className="text-xs text-surface-400 uppercase tracking-wider font-body">Critical</p>
          <p className={`font-display text-2xl mt-1 ${criticalCount > 0 ? 'text-red-400' : 'text-surface-400'}`}>
            {criticalCount}
          </p>
        </Card>
        <Card className="border-amber-500/20">
          <p className="text-xs text-surface-400 uppercase tracking-wider font-body">Warnings</p>
          <p className={`font-display text-2xl mt-1 ${warningCount > 0 ? 'text-amber-400' : 'text-surface-400'}`}>
            {warningCount}
          </p>
        </Card>
        <Card>
          <p className="text-xs text-surface-400 uppercase tracking-wider font-body">Info</p>
          <p className="font-display text-2xl mt-1 text-brand-400">{infoCount}</p>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Violations */}
        <div className="space-y-4">
          <SectionHeader title={`Active Violations (${violations.length})`} />
          {loading ? (
            <div className="flex justify-center py-8"><Spinner /></div>
          ) : violations.length === 0 ? (
            <Card>
              <div className="flex flex-col items-center py-8 text-center">
                <CheckCircle size={28} className="text-emerald-400 mb-3" />
                <p className="font-body font-medium text-white">No violations detected</p>
                <p className="text-sm text-surface-400 font-body mt-1">
                  Your portfolio is within all risk thresholds.
                </p>
              </div>
            </Card>
          ) : (
            <div className="space-y-3">
              {violations.map((v, i) => <ViolationCard key={i} v={v} />)}
            </div>
          )}
        </div>

        {/* Settings editor */}
        {settings && (
          <RiskSettingsEditor settings={settings} onSave={saveSettings} />
        )}
      </div>
    </div>
  )
}
