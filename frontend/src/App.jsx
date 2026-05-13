import React, { createContext, useContext, useState } from 'react'
import { BrowserRouter as Router, Routes, Route, NavLink } from 'react-router-dom'
import { API_URL } from './services/api'
import {
  LayoutDashboard, Users, Search, Activity, Bell,
  Settings as SettingsIcon, Moon, Sun, Menu, X, AlertTriangle
} from 'lucide-react'

import Overview from './pages/Overview'
import ActiveTraders from './pages/ActiveTraders'
import Discovery from './pages/Discovery'
import Health from './pages/Health'
import Alerts from './pages/Alerts'
import SettingsPage from './pages/Settings'

const ThemeContext = createContext({ dark: true, toggle: () => {} })
export const useTheme = () => useContext(ThemeContext)

const PortfolioContext = createContext({ portfolioId: 1 })
export const usePortfolio = () => useContext(PortfolioContext)

const NAV_ITEMS = [
  { path: '/',            icon: LayoutDashboard, label: 'Overview'      },
  { path: '/traders',     icon: Users,            label: 'Active Traders'},
  { path: '/discovery',   icon: Search,           label: 'Discovery'     },
  { path: '/health',      icon: Activity,         label: 'Health'        },
  { path: '/alerts',      icon: Bell,             label: 'Alerts'        },
  { path: '/settings',    icon: SettingsIcon,     label: 'Settings'      },
]

function Sidebar({ open, onClose }) {
  const { dark, toggle } = useTheme()

  return (
    <>
      {open && (
        <div className="fixed inset-0 bg-black/60 z-20 lg:hidden" onClick={onClose} />
      )}
      <aside className={`
        fixed left-0 top-0 h-full w-64 z-30 flex flex-col
        transition-transform duration-300
        ${open ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'}
        bg-surface-950 border-r border-surface-800
      `}>
        <div className="p-6 border-b border-surface-800 flex items-center justify-between">
          <div>
            <div className="flex items-center gap-2">
              <div className="w-7 h-7 rounded-lg bg-brand-500 flex items-center justify-center">
                <Activity size={16} className="text-white" />
              </div>
              <span className="font-display text-white text-lg tracking-tight">Portfolio</span>
            </div>
            <p className="text-xs text-surface-400 mt-1 font-body ml-9">Smart Assistant</p>
          </div>
          <button onClick={onClose} className="lg:hidden text-surface-400 hover:text-white">
            <X size={18} />
          </button>
        </div>

        <nav className="flex-1 p-4 space-y-1">
          {NAV_ITEMS.map(({ path, icon: Icon, label }) => (
            <NavLink
              key={path}
              to={path}
              end={path === '/'}
              onClick={onClose}
              className={({ isActive }) => `
                flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-body
                transition-all duration-150
                ${isActive
                  ? 'bg-brand-500/15 text-brand-400 font-medium'
                  : 'text-surface-400 hover:text-white hover:bg-surface-800'
                }
              `}
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </nav>

        <div className="p-4 border-t border-surface-800 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-full bg-brand-500/20 flex items-center justify-center">
              <span className="text-xs text-brand-400 font-mono font-bold">U1</span>
            </div>
            <span className="text-xs text-surface-400">Portfolio #1</span>
          </div>
          <button
            onClick={toggle}
            className="p-2 rounded-lg text-surface-400 hover:text-white hover:bg-surface-800 transition-colors"
          >
            {dark ? <Sun size={16} /> : <Moon size={16} />}
          </button>
        </div>
      </aside>
    </>
  )
}

function TopBar({ onMenuClick }) {
  return (
    <header className="sticky top-0 z-10 bg-surface-950/80 backdrop-blur-sm border-b border-surface-800 px-4 h-14 flex items-center justify-between lg:hidden">
      <button onClick={onMenuClick} className="text-surface-400 hover:text-white p-1">
        <Menu size={22} />
      </button>
      <div className="flex items-center gap-2">
        <div className="w-6 h-6 rounded-md bg-brand-500 flex items-center justify-center">
          <Activity size={13} className="text-white" />
        </div>
        <span className="font-display text-white text-base">Portfolio</span>
      </div>
      <div className="w-8" />
    </header>
  )
}

export default function App() {
  const [dark, setDark] = useState(true)
  const [sidebarOpen, setSidebarOpen] = useState(false)

  return (
    <ThemeContext.Provider value={{ dark, toggle: () => setDark(d => !d) }}>
      <PortfolioContext.Provider value={{ portfolioId: 1 }}>
        <div className={`${dark ? 'dark' : ''} font-body bg-surface-950 text-white min-h-screen`}>
          <Router>
            <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
            <div className="lg:pl-64 min-h-screen flex flex-col">
              <TopBar onMenuClick={() => setSidebarOpen(true)} />
              <main className="flex-1 p-4 lg:p-6 max-w-7xl mx-auto w-full">
                <Routes>
                  <Route path="/"          element={<Overview />} />
                  <Route path="/traders"   element={<ActiveTraders />} />
                  <Route path="/discovery" element={<Discovery />} />
                  <Route path="/health"    element={<Health />} />
                  <Route path="/alerts"    element={<Alerts />} />
                  <Route path="/settings"  element={<SettingsPage />} />
                </Routes>
              </main>
            </div>
          </Router>
        </div>
      </PortfolioContext.Provider>
    </ThemeContext.Provider>
  )
}
