import React, { useState, useEffect, useCallback } from 'react'
import { Bell, RefreshCw, CheckCheck, TrendingDown, Activity, AlertTriangle } from 'lucide-react'
import { alertsAPI } from '../services/api'
import { Card, PageHeader, Badge, Spinner, EmptyState } from '../components/common/ui'
import { usePortfolio } from '../App'

const SEVERITY_BADGE = {
  critical: 'red',
  warning: 'yellow',
  info: 'blue',
}

function AlertCard({ alert, onMarkRead }) {
  const typeColors = {
    monitoring: 'border-brand-500/20 bg-brand-500/5',
    drawdown: 'border-red-500/20 bg-red-500/5',
    trader_risk: 'border-orange-500/20 bg-orange-500/5',
    ai_scout: 'border-blue-500/20 bg-blue-500/5',
  }
  const border = typeColors[alert.type] || 'border-surface-800 bg-transparent'

  return (
    <div className={`rounded-xl border p-4 transition-all ${alert.is_read ? 'opacity-60 border-surface-800 bg-transparent' : border}`}>
      <div className="flex items-start gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2 flex-wrap">
              <p className={`text-sm font-semibold ${alert.is_read ? 'text-surface-400' : 'text-white'}`}>
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
                <CheckCheck size={14} />
              </button>
            )}
          </div>
          <p className="text-xs text-surface-400 leading-relaxed mt-1">{alert.message}</p>
          <p className="text-xs text-surface-500 mt-2">
            {alert.created_at ? new Date(alert.created_at).toLocaleString() : ''}
            {alert.was_sent_telegram && (
              <span className="ml-2 text-brand-500">Sent to Telegram</span>
            )}
          </p>
        </div>
      </div>
    </div>
  )
}

export default function Alerts() {
  const { portfolioId } = usePortfolio()
  const [alerts, setAlerts] = useState([])
  const [summary, setSummary] = useState(null)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('all')

  const fetchAlerts = useCallback(async () => {
    setLoading(true)
    try {
      const data = await alertsAPI.list(portfolioId)
      setAlerts(data)
      const s = await alertsAPI.summary(portfolioId)
      setSummary(s)
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
    try {
      await alertsAPI.markAllRead(portfolioId)
      setAlerts(as => as.map(a => ({ ...a, is_read: true })))
      setSummary(prev => prev ? { ...prev, total: 0, critical: 0, warning: 0, info: 0 } : prev)
    } catch (e) {
      console.error('Mark all read failed:', e)
    }
  }

  const filtered = alerts.filter(a => {
    if (filter === 'unread') return !a.is_read
    if (filter === 'critical') return a.severity === 'critical'
    if (filter === 'warning') return a.severity === 'warning'
    return true
  })

  const unreadCount = alerts.filter(a => !a.is_read).length
  const s = summary || { total: 0, critical: 0, warning: 0, info: 0 }

  const filters = [
    { key: 'all', label: `All (${alerts.length})` },
    { key: 'unread', label: `Unread (${unreadCount})` },
    { key: 'critical', label: `Critical (${s.critical})` },
    { key: 'warning', label: `Warning (${s.warning})` },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="Alerts"
        subtitle="Important notifications about your portfolio"
        actions={
          <div className="flex items-center gap-2">
            <button onClick={fetchAlerts} className="p-1.5 bg-surface-800 hover:bg-surface-700 border border-surface-700 rounded-lg text-surface-400 hover:text-white transition-colors">
              <RefreshCw size={14} />
            </button>
            {unreadCount > 0 && (
              <button onClick={markAllRead} className="flex items-center gap-1.5 px-3 py-1.5 bg-surface-800 hover:bg-surface-700 border border-surface-700 rounded-lg text-xs text-surface-300 transition-colors">
                <CheckCheck size={13} /> Mark all read
              </button>
            )}
          </div>
        }
      />

      <div className="grid grid-cols-3 gap-4">
        <Card className="border-red-500/20">
          <p className="text-xs text-surface-400 uppercase tracking-wider">Critical</p>
          <p className={`font-display text-2xl mt-1 ${s.critical > 0 ? 'text-red-400' : 'text-surface-400'}`}>{s.critical}</p>
        </Card>
        <Card className="border-amber-500/20">
          <p className="text-xs text-surface-400 uppercase tracking-wider">Warnings</p>
          <p className={`font-display text-2xl mt-1 ${s.warning > 0 ? 'text-amber-400' : 'text-surface-400'}`}>{s.warning}</p>
        </Card>
        <Card>
          <p className="text-xs text-surface-400 uppercase tracking-wider">Unread</p>
          <p className={`font-display text-2xl mt-1 ${unreadCount > 0 ? 'text-brand-400' : 'text-surface-400'}`}>{unreadCount}</p>
        </Card>
      </div>

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

      {loading ? (
        <div className="flex justify-center py-12"><Spinner size="lg" /></div>
      ) : filtered.length === 0 ? (
        <EmptyState icon={Bell} title="No alerts" description={filter === 'all' ? 'No alerts yet.' : `No ${filter} alerts found.`} />
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
