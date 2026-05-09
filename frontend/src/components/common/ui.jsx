/**
 * Shared UI Components
 * Clean, minimal card-based design system.
 */

import React from 'react'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'
import { clsx } from 'clsx'

// ──────────────────────────────────────────────
// Card
// ──────────────────────────────────────────────
export function Card({ children, className, ...props }) {
  return (
    <div
      className={clsx(
        'bg-surface-900 border border-surface-800 rounded-xl p-5',
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
}

// ──────────────────────────────────────────────
// Page header
// ──────────────────────────────────────────────
export function PageHeader({ title, subtitle, actions }) {
  return (
    <div className="flex items-start justify-between mb-6">
      <div>
        <h1 className="font-display text-2xl text-white tracking-tight">{title}</h1>
        {subtitle && <p className="text-sm text-surface-400 mt-1 font-body">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}

// ──────────────────────────────────────────────
// Stat card
// ──────────────────────────────────────────────
export function StatCard({ label, value, subvalue, trend, icon: Icon, colorClass }) {
  const trendColor = trend > 0 ? 'text-emerald-400' : trend < 0 ? 'text-red-400' : 'text-surface-400'
  const TrendIcon = trend > 0 ? TrendingUp : trend < 0 ? TrendingDown : Minus

  return (
    <Card>
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <p className="text-xs text-surface-400 uppercase tracking-wider font-body">{label}</p>
          <p className="font-display text-xl text-white mt-1 truncate">{value}</p>
          {subvalue && (
            <div className={clsx('flex items-center gap-1 mt-1', trendColor)}>
              <TrendIcon size={12} />
              <span className="text-xs font-body">{subvalue}</span>
            </div>
          )}
        </div>
        {Icon && (
          <div className={clsx('w-9 h-9 rounded-lg flex items-center justify-center', colorClass || 'bg-brand-500/15')}>
            <Icon size={18} className={colorClass ? 'text-white' : 'text-brand-400'} />
          </div>
        )}
      </div>
    </Card>
  )
}

// ──────────────────────────────────────────────
// Badge
// ──────────────────────────────────────────────
const BADGE_STYLES = {
  green:   'bg-emerald-500/15 text-emerald-400 border-emerald-500/20',
  red:     'bg-red-500/15 text-red-400 border-red-500/20',
  yellow:  'bg-amber-500/15 text-amber-400 border-amber-500/20',
  blue:    'bg-brand-500/15 text-brand-400 border-brand-500/20',
  gray:    'bg-surface-700/50 text-surface-300 border-surface-700',
  purple:  'bg-purple-500/15 text-purple-400 border-purple-500/20',
}

export function Badge({ children, variant = 'gray', className }) {
  return (
    <span className={clsx(
      'inline-flex items-center px-2 py-0.5 rounded-md text-xs font-body border',
      BADGE_STYLES[variant] || BADGE_STYLES.gray,
      className
    )}>
      {children}
    </span>
  )
}

// ──────────────────────────────────────────────
// Health score ring
// ──────────────────────────────────────────────
export function HealthRing({ score, size = 80 }) {
  const radius = (size - 10) / 2
  const circumference = 2 * Math.PI * radius
  const filled = (score / 100) * circumference

  const color = score >= 70 ? '#10b981' : score >= 45 ? '#f59e0b' : '#ef4444'

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        <circle cx={size/2} cy={size/2} r={radius} fill="none" stroke="#1e293b" strokeWidth={8} />
        <circle
          cx={size/2} cy={size/2} r={radius}
          fill="none" stroke={color} strokeWidth={8}
          strokeDasharray={`${filled} ${circumference - filled}`}
          strokeLinecap="round"
          style={{ transition: 'stroke-dasharray 1s ease' }}
        />
      </svg>
      <div className="absolute text-center">
        <p className="font-mono text-sm font-bold text-white">{Math.round(score)}</p>
      </div>
    </div>
  )
}

// ──────────────────────────────────────────────
// Risk pill
// ──────────────────────────────────────────────
export function RiskPill({ level }) {
  const styles = {
    conservative: 'green',
    balanced:     'blue',
    aggressive:   'yellow',
    high_risk:    'red',
  }
  const labels = {
    conservative: 'Conservative',
    balanced:     'Balanced',
    aggressive:   'Aggressive',
    high_risk:    'High Risk',
  }
  return <Badge variant={styles[level] || 'gray'}>{labels[level] || level}</Badge>
}

// ──────────────────────────────────────────────
// PnL display
// ──────────────────────────────────────────────
export function PnlDisplay({ value, currency = 'USD', prefix, showSign = true, className }) {
  const isPositive = value >= 0
  const color = isPositive ? 'text-emerald-400' : 'text-red-400'
  const sign = showSign ? (isPositive ? '+' : '') : ''
  const finalPrefix = prefix !== undefined ? prefix : (currency === 'EUR' ? '€' : '$')

  return (
    <span className={clsx(color, className, 'font-mono')}>
      {sign}{finalPrefix}{Math.abs(value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
    </span>
  )
}

// ──────────────────────────────────────────────
// Loading spinner
// ──────────────────────────────────────────────
export function Spinner({ size = 'md' }) {
  const sizeClass = { sm: 'w-4 h-4', md: 'w-6 h-6', lg: 'w-8 h-8' }[size]
  return (
    <div className={clsx('border-2 border-surface-700 border-t-brand-500 rounded-full animate-spin', sizeClass)} />
  )
}

// ──────────────────────────────────────────────
// Empty state
// ──────────────────────────────────────────────
export function EmptyState({ icon: Icon, title, description }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 text-center">
      {Icon && <Icon size={32} className="text-surface-600 mb-3" />}
      <p className="text-surface-300 font-body font-medium">{title}</p>
      {description && <p className="text-sm text-surface-500 mt-1 font-body max-w-xs">{description}</p>}
    </div>
  )
}

// ──────────────────────────────────────────────
// Toggle switch
// ──────────────────────────────────────────────
export function Toggle({ checked, onChange, disabled }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => !disabled && onChange(!checked)}
      className={clsx(
        'relative inline-flex h-5 w-9 items-center rounded-full transition-colors',
        checked ? 'bg-brand-500' : 'bg-surface-700',
        disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'
      )}
    >
      <span className={clsx(
        'inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform',
        checked ? 'translate-x-4.5' : 'translate-x-0.5'
      )} />
    </button>
  )
}

// ──────────────────────────────────────────────
// Section header
// ──────────────────────────────────────────────
export function SectionHeader({ title, action }) {
  return (
    <div className="flex items-center justify-between mb-4">
      <h2 className="text-sm font-semibold text-surface-200 uppercase tracking-wider font-body">{title}</h2>
      {action}
    </div>
  )
}
