/**
 * Alerts Page
 * All system alerts with severity filtering and read/unread management.
 */

import React, { useState, useEffect, useCallback } from 'react'
import {
  Bell, RefreshCw, CheckCheck, AlertTriangle,
  Info, TrendingDown, Activity, Zap, BarChart3, CheckCircle
} from 'lucide-react'
import { alertsAPI } from '../services/api'
import { Card, PageHeader, Badge, Spinner, EmptyState, SectionHeader } from '../components/common/ui'
import { usePortfolio } from '../App'

// ──────────────────────────────────────────────
// Alert type configs
// ──────────────────────────────────────────────
const ALERT_TYPE_CFG = {
  drawdown:         { icon: TrendingDown, color: 'text-red-400',    bg: 'bg-red-500/5',     border: 'border-red-500/20'    },
  profit_milestone: { icon: TrendingDown, color: 'text-emerald-400',bg: 'bg-emerald-500/5', border: 'border-emerald-500/20' },
  volatility:       { icon: Activity,     color: 'text-amber-400',  bg: 'bg-amber-500/5',   border: 'border-amber-500/20'   },
  trader_risk:      { icon: AlertTriangle,color: 'text-orange-400', bg: 'bg-orange-500/5',  border: 'border-orange-500/20'  },
  imbalance:        { icon: BarChart3,    color: 'text-purple-400', bg: 'bg-purple-500/5',  border: 'border-purple-500/20'  },
  automation:       { icon: Zap,          color: 'text-brand-400',  bg: 'bg-brand-500/5',   border: 'border-brand-500/20'   },
  weekly_summary:   { icon: BarChart3,    color: 'text-brand-400',  bg: 'bg-brand-500/5',   border: 'border-brand-500/20'   },
}

const SEVERITY_BADGE = {
  critical: 'red',
  warning:  'yellow',
  info:     'blue',
}

// ──────────────────────────────────────────────
// Single alert card
// ──────────────────────────────────────────────
function AlertCard({ alert, onMarkRead }) {
  const cfg = ALERT_TYPE_CFG[alert.alert_type] || ALERT_TYPE_CFG.volatility
  const Icon = cfg.icon

  return (
    <div className={`
      rounded-xl border p-4 transition-all
      ${alert.is_read ? 'opacity-60 border-surface-800 bg-transparent' : `${cfg.border} ${cfg.bg}`}
    `}>
      <div className="flex items-start gap-3">
        <Icon size={18} className={`${cfg.color} shrink-0 mt-0.5`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2 flex-wrap">
              <p className={`text-sm font-semibold font-body ${alert.is_read ? 'text-surface-400' : 'text-white'}`}>
                {alert.title}
              </p>
              <Badge variant={SEVERITY_BADGE[alert.severity] || 'gray'}>{alert.severity}</Badge>
              {!alert.is_read && (
                <span className="w-1.5 h-1.5 rounded-full bg-brand-500 inline-block" />
              )}
            </div>
            {!alert.is_read && (
              <button
                onClick={() => onMarkRead(alert.id)}
                className="shrink-0 p-1.5 text-surface-500 hover:text-emerald-400 hover:bg-emerald-500/10 rounded-lg transition-colors"
                title="Mark as read"
              >
                <CheckCircle size={14} />
              </button>
            )}
          </div>
          <p className="text-xs text-surface-400 font-body leading-relaxed mt-1">{alert.message}</p>
          <p className="text-xs text-surface-500 font-body mt-2">
            {new Date(alert.created_at).toLocaleString()}
            {alert.was_sent_telegram && (
              <span className="ml-2 text-brand-500">✓ Sent to Telegram</span>
            )}
          </p>
        </div>
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────
// Main Alerts page
// ──────────────────────────────────────────────
export default function Alerts() {
  const { portfolioId } = usePortfolio()
  const [alerts,   setAlerts]   = useState([])
  const [loading,  setLoading]  = useState(true)
  const [filter,   setFilter]   = useState('all')   // all | unread | critical | warning | info

  const fetchAlerts = useCallback(async () => {
    setLoading(true)
    try {
      const data = await alertsAPI.list(portfolioId)
      setAlerts(data)
    } catch (e) {
      console.error('Alerts load failed:', e)
    } finally {
      setLoading(false)
    }
  }, [portfolioId])

  useEffect(() => { fetchAlerts() }, [fetchAlerts])

  const markRead = async (alertId) => {
    try {
      await alertsAPI.markRead(alertId)
      setAlerts(as => as.map(a => a.id === alertId ? { ...a, is_read: true } : a))
    } catch (e) {
      console.error('Mark read failed:', e)
    }
  }

  const markAllRead = async () => {
    const unread = alerts.filter(a => !a.is_read)
    await Promise.all(unread.map(a => alertsAPI.markRead(a.id)))
    setAlerts(as => as.map(a => ({ ...a, is_read: true })))
  }

  const filtered = alerts.filter(a => {
    if (filter === 'unread')   return !a.is_read
    if (filter === 'critical') return a.severity === 'critical'
    if (filter === 'warning')  return a.severity === 'warning'
    if (filter === 'info')     return a.severity === 'info'
    return true
  })

  const unreadCount    = alerts.filter(a => !a.is_read).length
  const criticalCount  = alerts.filter(a => a.severity === 'critical').length
  const warningCount   = alerts.filter(a => a.severity === 'warning').length

  const filters = [
    { key: 'all',      label: `All (${alerts.length})`        },
    { key: 'unread',   label: `Unread (${unreadCount})`        },
    { key: 'critical', label: `Critical (${criticalCount})`    },
    { key: 'warning',  label: `Warning (${warningCount})`      },
    { key: 'info',     label: `Info`                           },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="Alerts"
        subtitle="Risk alerts, milestones, and automation notifications"
        actions={
          <div className="flex items-center gap-2">
            <button onClick={fetchAlerts} className="p-1.5 bg-surface-800 hover:bg-surface-700 border border-surface-700 rounded-lg text-surface-400 hover:text-white transition-colors">
              <RefreshCw size={14} />
            </button>
            {unreadCount > 0 && (
              <button
                onClick={markAllRead}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-surface-800 hover:bg-surface-700 border border-surface-700 rounded-lg text-xs text-surface-300 transition-colors"
              >
                <CheckCheck size={13} /> Mark all read
              </button>
            )}
          </div>
        }
      />

      {/* Summary row */}
      <div className="grid grid-cols-3 gap-4">
        <Card className="border-red-500/20">
          <p className="text-xs text-surface-400 uppercase tracking-wider font-body">Critical</p>
          <p className={`font-display text-2xl mt-1 ${criticalCount > 0 ? 'text-red-400' : 'text-surface-400'}`}>{criticalCount}</p>
        </Card>
        <Card className="border-amber-500/20">
          <p className="text-xs text-surface-400 uppercase tracking-wider font-body">Warnings</p>
          <p className={`font-display text-2xl mt-1 ${warningCount > 0 ? 'text-amber-400' : 'text-surface-400'}`}>{warningCount}</p>
        </Card>
        <Card>
          <p className="text-xs text-surface-400 uppercase tracking-wider font-body">Unread</p>
          <p className={`font-display text-2xl mt-1 ${unreadCount > 0 ? 'text-brand-400' : 'text-surface-400'}`}>{unreadCount}</p>
        </Card>
      </div>

      {/* Filter tabs */}
      <div className="flex gap-2 flex-wrap">
        {filters.map(f => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={`px-3 py-1.5 rounded-lg text-xs font-body transition-colors ${
              filter === f.key
                ? 'bg-brand-500/20 text-brand-400 border border-brand-500/30'
                : 'text-surface-400 hover:text-white border border-surface-700 hover:border-surface-600'
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {/* Alert list */}
      {loading ? (
        <div className="flex justify-center py-12"><Spinner size="lg" /></div>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon={Bell}
          title="No alerts"
          description={filter === 'all'
            ? 'No alerts have been generated yet. Run a risk check to detect potential issues.'
            : `No ${filter} alerts found.`
          }
        />
      ) : (
        <div className="space-y-3">
          {filtered.map(a => (
            <AlertCard key={a.id} alert={a} onMarkRead={markRead} />
          ))}
        </div>
      )}
    </div>
  )
}
