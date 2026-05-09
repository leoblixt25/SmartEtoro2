/**
 * Automation Page
 * Manage automation rules with full audit trail, toggles, and emergency stop.
 */

import React, { useState, useEffect, useCallback } from 'react'
import {
  Zap, StopCircle, RefreshCw, Plus, Clock, CheckCircle,
  XCircle, RotateCcw, AlertTriangle, ChevronDown, ChevronUp
} from 'lucide-react'
import { automationAPI } from '../services/api'
import {
  Card, PageHeader, Badge, Spinner, EmptyState,
  SectionHeader, Toggle
} from '../components/common/ui'
import { usePortfolio } from '../App'

// ──────────────────────────────────────────────
// Rule type definitions
// ──────────────────────────────────────────────
const RULE_TYPES = [
  {
    type: 'take_profit',
    name: 'Auto Take-Profit',
    description: 'Propose closing positions when unrealized returns reach a threshold.',
    defaultThreshold: 20,
    thresholdLabel: 'Return % trigger',
    icon: '📈',
  },
  {
    type: 'partial_profit_lock',
    name: 'Partial Profit Lock',
    description: 'Lock a percentage of gains before a full reversal.',
    defaultThreshold: 15,
    thresholdLabel: 'Return % trigger',
    icon: '🔒',
  },
  {
    type: 'reduce_on_drawdown',
    name: 'Reduce on Drawdown',
    description: 'Propose allocation reduction after a drawdown event.',
    defaultThreshold: 10,
    thresholdLabel: 'Drawdown % trigger',
    icon: '📉',
  },
  {
    type: 'pause_copy_on_loss',
    name: 'Pause Copy on Loss',
    description: 'Propose pausing copy relationship when a trader underperforms.',
    defaultThreshold: -10,
    thresholdLabel: 'Return % below which to flag',
    icon: '⏸',
  },
  {
    type: 'rebalance',
    name: 'Auto Rebalance',
    description: 'Flag drift from target allocations.',
    defaultThreshold: 5,
    thresholdLabel: 'Drift % trigger',
    icon: '⚖️',
  },
  {
    type: 'reduce_on_volatility',
    name: 'Reduce on Volatility',
    description: 'Propose exposure reduction when trader volatility spikes.',
    defaultThreshold: 30,
    thresholdLabel: 'Volatility % trigger',
    icon: '🌊',
  },
]

// ──────────────────────────────────────────────
// Status badge helper
// ──────────────────────────────────────────────
function StatusBadge({ status }) {
  const cfg = {
    enabled:  { label: 'Enabled',  variant: 'green'  },
    disabled: { label: 'Disabled', variant: 'gray'   },
    paused:   { label: 'Paused',   variant: 'yellow' },
  }[status] || { label: status, variant: 'gray' }
  return <Badge variant={cfg.variant}>{cfg.label}</Badge>
}

// ──────────────────────────────────────────────
// Rule card
// ──────────────────────────────────────────────
function RuleCard({ rule, onToggle, portfolioId }) {
  const def = RULE_TYPES.find(r => r.type === rule.rule_type)
  const isEnabled = rule.status === 'enabled'

  return (
    <div className="border border-surface-700 rounded-xl p-4 hover:border-surface-600 transition-colors">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0">
          <span className="text-xl shrink-0 mt-0.5">{def?.icon || '⚙️'}</span>
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <p className="font-body font-semibold text-white text-sm">{rule.name}</p>
              <StatusBadge status={rule.status} />
              {rule.requires_approval && (
                <Badge variant="blue">Approval Required</Badge>
              )}
            </div>
            <p className="text-xs text-surface-400 font-body mt-1 leading-relaxed">
              {rule.description || def?.description}
            </p>
            <div className="flex flex-wrap gap-4 mt-2">
              {rule.threshold != null && (
                <span className="text-xs text-surface-400 font-body">
                  Threshold: <span className="text-surface-200 font-mono">{rule.threshold}</span>
                </span>
              )}
              <span className="text-xs text-surface-400 font-body">
                Cooldown: <span className="text-surface-200 font-mono">{rule.cooldown_hours}h</span>
              </span>
              <span className="text-xs text-surface-400 font-body">
                Triggered: <span className="text-surface-200 font-mono">{rule.trigger_count}×</span>
              </span>
            </div>
          </div>
        </div>
        <div className="shrink-0">
          <Toggle
            checked={isEnabled}
            onChange={() => onToggle(rule.id)}
            disabled={rule.status === 'paused'}
          />
        </div>
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────
// Add rule modal / form
// ──────────────────────────────────────────────
function AddRuleForm({ portfolioId, onAdd, onClose }) {
  const [selected, setSelected] = useState(RULE_TYPES[0].type)
  const [threshold, setThreshold] = useState('')
  const [cooldown,  setCooldown]  = useState(24)
  const [requiresApproval, setRequiresApproval] = useState(true)
  const [saving, setSaving] = useState(false)

  const def = RULE_TYPES.find(r => r.type === selected)

  const handleSubmit = async () => {
    setSaving(true)
    try {
      const rule = await automationAPI.createRule(portfolioId, {
        rule_type: selected,
        name: def.name,
        description: def.description,
        threshold: threshold !== '' ? parseFloat(threshold) : def.defaultThreshold,
        cooldown_hours: cooldown,
        requires_approval: requiresApproval,
        config: {},
      })
      onAdd(rule)
      onClose()
    } catch (e) {
      console.error('Create rule failed:', e)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/70 z-50 flex items-center justify-center p-4">
      <Card className="w-full max-w-md">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-display text-lg text-white">Add Automation Rule</h2>
          <button onClick={onClose} className="text-surface-400 hover:text-white"><XCircle size={20} /></button>
        </div>

        <div className="space-y-4">
          {/* Rule type selector */}
          <div>
            <label className="text-xs text-surface-400 font-body block mb-2">Rule Type</label>
            <div className="grid grid-cols-2 gap-2">
              {RULE_TYPES.map(r => (
                <button
                  key={r.type}
                  onClick={() => { setSelected(r.type); setThreshold(String(r.defaultThreshold)) }}
                  className={`p-2.5 rounded-lg border text-left transition-colors ${
                    selected === r.type
                      ? 'border-brand-500/50 bg-brand-500/10'
                      : 'border-surface-700 hover:border-surface-600'
                  }`}
                >
                  <span className="text-lg">{r.icon}</span>
                  <p className="text-xs text-white font-body mt-1 leading-tight">{r.name}</p>
                </button>
              ))}
            </div>
          </div>

          {/* Threshold */}
          <div>
            <label className="text-xs text-surface-400 font-body block mb-1">
              {def?.thresholdLabel} (default: {def?.defaultThreshold})
            </label>
            <input
              type="number"
              value={threshold}
              onChange={e => setThreshold(e.target.value)}
              placeholder={String(def?.defaultThreshold)}
              className="w-full bg-surface-800 border border-surface-700 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-brand-500"
            />
          </div>

          {/* Cooldown */}
          <div>
            <label className="text-xs text-surface-400 font-body block mb-1">Cooldown (hours)</label>
            <input
              type="number"
              value={cooldown}
              onChange={e => setCooldown(parseInt(e.target.value))}
              className="w-full bg-surface-800 border border-surface-700 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-brand-500"
            />
          </div>

          {/* Approval required */}
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-surface-200 font-body">Require Approval</p>
              <p className="text-xs text-surface-500 font-body">Rule proposes action — you approve before execution.</p>
            </div>
            <Toggle checked={requiresApproval} onChange={setRequiresApproval} />
          </div>

          <button
            onClick={handleSubmit}
            disabled={saving}
            className="w-full py-2.5 bg-brand-500 hover:bg-brand-600 text-white rounded-lg text-sm font-body font-medium transition-colors flex items-center justify-center gap-2"
          >
            {saving ? <Spinner size="sm" /> : <Plus size={14} />}
            Add Rule
          </button>
        </div>
      </Card>
    </div>
  )
}

// ──────────────────────────────────────────────
// Audit log table
// ──────────────────────────────────────────────
function AuditLog({ logs, portfolioId, onReverse }) {
  return (
    <div className="space-y-2">
      {logs.length === 0 ? (
        <EmptyState icon={Clock} title="No automation actions yet" description="Actions taken by automation rules appear here." />
      ) : (
        logs.map(log => (
          <div key={log.id} className="flex items-start justify-between gap-3 py-3 border-b border-surface-800 last:border-0">
            <div className="flex items-start gap-3 min-w-0">
              <div className={`mt-1 w-2 h-2 rounded-full shrink-0 ${
                log.was_reversed ? 'bg-surface-600' :
                log.was_approved ? 'bg-emerald-500' : 'bg-amber-500'
              }`} />
              <div className="min-w-0">
                <p className="text-xs font-mono text-surface-300 truncate">{log.action_type}</p>
                <p className="text-xs text-surface-400 font-body leading-relaxed mt-0.5">{log.description}</p>
                <div className="flex items-center gap-2 mt-1 flex-wrap">
                  <span className="text-xs text-surface-500 font-body">
                    {new Date(log.triggered_at).toLocaleString()}
                  </span>
                  {log.was_simulated && <Badge variant="blue">Simulation</Badge>}
                  {log.was_reversed && <Badge variant="gray">Reversed</Badge>}
                </div>
              </div>
            </div>
            {log.was_approved && !log.was_reversed && (
              <button
                onClick={() => onReverse(log.id)}
                className="shrink-0 p-1.5 text-surface-500 hover:text-amber-400 hover:bg-amber-500/10 rounded-lg transition-colors"
                title="Reverse this action"
              >
                <RotateCcw size={14} />
              </button>
            )}
          </div>
        ))
      )}
    </div>
  )
}

// ──────────────────────────────────────────────
// Emergency stop banner
// ──────────────────────────────────────────────
function EmergencyStopBanner({ onStop }) {
  const [confirm, setConfirm] = useState(false)
  const [stopping, setStopping] = useState(false)

  const handleStop = async () => {
    setStopping(true)
    try {
      await onStop()
    } finally {
      setStopping(false)
      setConfirm(false)
    }
  }

  return (
    <div className="bg-red-500/5 border border-red-500/20 rounded-xl p-4 flex items-center justify-between gap-4">
      <div className="flex items-center gap-3">
        <StopCircle size={20} className="text-red-400 shrink-0" />
        <div>
          <p className="text-sm font-semibold text-white font-body">Emergency Stop</p>
          <p className="text-xs text-surface-400 font-body mt-0.5">
            Immediately pause all automation rules. Individual rules can be re-enabled from the dashboard.
          </p>
        </div>
      </div>
      <div className="shrink-0">
        {!confirm ? (
          <button
            onClick={() => setConfirm(true)}
            className="px-3 py-1.5 bg-red-500/20 hover:bg-red-500/30 border border-red-500/30 text-red-400 rounded-lg text-xs font-body transition-colors"
          >
            Activate
          </button>
        ) : (
          <div className="flex items-center gap-2">
            <span className="text-xs text-red-400 font-body">Confirm?</span>
            <button onClick={handleStop} disabled={stopping}
              className="px-2 py-1 bg-red-500 text-white rounded-lg text-xs font-body">
              {stopping ? '…' : 'Yes'}
            </button>
            <button onClick={() => setConfirm(false)}
              className="px-2 py-1 bg-surface-700 text-surface-300 rounded-lg text-xs font-body">
              No
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────
// Main Automation page
// ──────────────────────────────────────────────
export default function Automation() {
  const { portfolioId } = usePortfolio()
  const [rules,    setRules]    = useState([])
  const [logs,     setLogs]     = useState([])
  const [loading,  setLoading]  = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [showLogs, setShowLogs] = useState(true)

  const fetchAll = useCallback(async () => {
    setLoading(true)
    try {
      const [r, l] = await Promise.all([
        automationAPI.listRules(portfolioId),
        automationAPI.getLogs(portfolioId, 20),
      ])
      setRules(r)
      setLogs(l)
    } catch (e) {
      console.error('Automation load failed:', e)
    } finally {
      setLoading(false)
    }
  }, [portfolioId])

  useEffect(() => { fetchAll() }, [fetchAll])

  const handleToggle = async (ruleId) => {
    try {
      const result = await automationAPI.toggleRule(portfolioId, ruleId)
      setRules(rs => rs.map(r => r.id === ruleId ? { ...r, status: result.new_status } : r))
    } catch (e) {
      console.error('Toggle failed:', e)
    }
  }

  const handleEmergencyStop = async () => {
    await automationAPI.emergencyStop(portfolioId)
    fetchAll()
  }

  const handleReverse = async (logId) => {
    try {
      await automationAPI.reverseAction(logId, portfolioId)
      setLogs(ls => ls.map(l => l.id === logId ? { ...l, was_reversed: true } : l))
    } catch (e) {
      console.error('Reverse failed:', e)
    }
  }

  const enabledCount  = rules.filter(r => r.status === 'enabled').length
  const pausedCount   = rules.filter(r => r.status === 'paused').length

  return (
    <div className="space-y-6">
      <PageHeader
        title="Automation"
        subtitle="Configurable rules with approval flow and full audit trail"
        actions={
          <div className="flex items-center gap-2">
            <button onClick={fetchAll} className="p-1.5 bg-surface-800 hover:bg-surface-700 border border-surface-700 rounded-lg text-surface-400 hover:text-white transition-colors">
              <RefreshCw size={14} />
            </button>
            <button
              onClick={() => setShowForm(true)}
              className="flex items-center gap-2 px-3 py-1.5 bg-brand-500 hover:bg-brand-600 text-white rounded-lg text-xs font-body transition-colors"
            >
              <Plus size={13} /> Add Rule
            </button>
          </div>
        }
      />

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4">
        <Card>
          <p className="text-xs text-surface-400 uppercase tracking-wider font-body">Total Rules</p>
          <p className="font-display text-2xl mt-1 text-white">{rules.length}</p>
        </Card>
        <Card>
          <p className="text-xs text-surface-400 uppercase tracking-wider font-body">Active</p>
          <p className={`font-display text-2xl mt-1 ${enabledCount > 0 ? 'text-emerald-400' : 'text-surface-400'}`}>{enabledCount}</p>
        </Card>
        <Card>
          <p className="text-xs text-surface-400 uppercase tracking-wider font-body">Paused</p>
          <p className={`font-display text-2xl mt-1 ${pausedCount > 0 ? 'text-amber-400' : 'text-surface-400'}`}>{pausedCount}</p>
        </Card>
      </div>

      {/* Emergency stop */}
      <EmergencyStopBanner onStop={handleEmergencyStop} />

      {/* Warning callout */}
      <div className="bg-amber-500/5 border border-amber-500/15 rounded-xl p-4 flex items-start gap-3">
        <AlertTriangle size={16} className="text-amber-400 shrink-0 mt-0.5" />
        <p className="text-xs text-amber-200 font-body leading-relaxed">
          <span className="font-semibold">Safety note:</span> All automation rules are configured to <em>propose</em> actions,
          not execute them automatically unless approval is disabled. Every action is logged and reversible.
          Rules marked "Approval Required" will wait for your review before any position changes occur.
        </p>
      </div>

      {/* Rules list */}
      {loading ? (
        <div className="flex justify-center py-8"><Spinner size="lg" /></div>
      ) : (
        <Card>
          <SectionHeader
            title={`Rules (${rules.length})`}
            action={
              <button onClick={() => setShowForm(true)} className="text-xs text-brand-400 hover:text-brand-300 flex items-center gap-1">
                <Plus size={12} /> Add
              </button>
            }
          />
          {rules.length === 0 ? (
            <EmptyState icon={Zap} title="No rules configured" description="Add automation rules to start monitoring your portfolio automatically." />
          ) : (
            <div className="space-y-3">
              {rules.map(r => (
                <RuleCard key={r.id} rule={r} onToggle={handleToggle} portfolioId={portfolioId} />
              ))}
            </div>
          )}
        </Card>
      )}

      {/* Audit log */}
      <Card>
        <div
          className="flex items-center justify-between cursor-pointer"
          onClick={() => setShowLogs(s => !s)}
        >
          <SectionHeader title={`Audit Log (${logs.length} recent actions)`} />
          {showLogs ? <ChevronUp size={16} className="text-surface-400" /> : <ChevronDown size={16} className="text-surface-400" />}
        </div>
        {showLogs && (
          <AuditLog logs={logs} portfolioId={portfolioId} onReverse={handleReverse} />
        )}
      </Card>

      {/* Add rule modal */}
      {showForm && (
        <AddRuleForm
          portfolioId={portfolioId}
          onAdd={rule => setRules(rs => [...rs, rule])}
          onClose={() => setShowForm(false)}
        />
      )}
    </div>
  )
}
