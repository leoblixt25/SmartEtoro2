import React, { useState, useEffect } from 'react'
import { Save, Key, MessageSquare, User, AlertCircle, CheckCircle } from 'lucide-react'
import { API_URL } from '../services/api'

export default function Settings() {
  const [settings, setSettings] = useState({
    etoro_api_key: '',
    etoro_api_secret: '',
    etoro_account_id: '',
    telegram_bot_token: '',
    telegram_chat_id: '',
    is_simulation: true
  })

  const [saving, setSaving] = useState(false)
  const [loading, setLoading] = useState(true)
  const [message, setMessage] = useState('')

  useEffect(() => {
    const loadSettings = async () => {
      try {
        const response = await fetch(`${API_URL}/api/settings`)
        if (response.ok) {
          const data = await response.json()
          setSettings(data)
        } else {
          setMessage('Failed to load settings from server')
        }
      } catch (error) {
        console.error('Failed to load settings:', error)
        setMessage('Failed to connect to server. Please check your connection.')
      } finally {
        setLoading(false)
      }
    }
    loadSettings()
  }, [])

  const handleSave = async () => {
    setSaving(true)
    setMessage('')

    try {
      const response = await fetch(`${API_URL}/api/settings`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(settings),
      })

      if (response.ok) {
        setMessage('Settings saved successfully!')
        setTimeout(() => setMessage(''), 3000)
      } else {
        const error = await response.json()
        setMessage(error.detail || 'Failed to save settings')
      }
    } catch (error) {
      console.error('Failed to save settings:', error)
      setMessage('Failed to connect to server. Please check your connection.')
    } finally {
      setSaving(false)
    }
  }

  const handleInputChange = (field, value) => {
    setSettings(prev => ({ ...prev, [field]: value }))
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-96">
        <div className="text-center">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto mb-4"></div>
          <p className="text-surface-400">Loading settings...</p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-display font-bold text-white mb-2">Settings</h1>
        <p className="text-surface-400 text-sm">
          Configure your API keys and application preferences
        </p>
      </div>

      {/* Success/Error Message */}
      {message && (
        <div className={`p-4 rounded-lg flex items-center gap-3 ${
          message.includes('successfully')
            ? 'bg-green-500/10 border border-green-500/20 text-green-300'
            : 'bg-red-500/10 border border-red-500/20 text-red-300'
        }`}>
          {message.includes('successfully') ? (
            <CheckCircle size={18} />
          ) : (
            <AlertCircle size={18} />
          )}
          <span className="text-sm">{message}</span>
        </div>
      )}

      {/* eToro Settings */}
      <div className="bg-surface-900 rounded-xl border border-surface-800 p-6">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 rounded-lg bg-blue-500/20 flex items-center justify-center">
            <Key size={20} className="text-blue-400" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-white">eToro API</h2>
            <p className="text-surface-400 text-sm">Configure your eToro API credentials</p>
          </div>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-surface-300 mb-2">
              API Key
            </label>
            <input
              type="password"
              value={settings.etoro_api_key}
              onChange={(e) => handleInputChange('etoro_api_key', e.target.value)}
              placeholder="Enter your eToro API key"
              className="w-full px-3 py-2 bg-surface-800 border border-surface-700 rounded-lg text-white placeholder-surface-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-surface-300 mb-2">
              API Secret
            </label>
            <input
              type="password"
              value={settings.etoro_api_secret}
              onChange={(e) => handleInputChange('etoro_api_secret', e.target.value)}
              placeholder="Enter your eToro API secret"
              className="w-full px-3 py-2 bg-surface-800 border border-surface-700 rounded-lg text-white placeholder-surface-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-surface-300 mb-2">
              Account ID (Optional)
            </label>
            <input
              type="text"
              value={settings.etoro_account_id}
              onChange={(e) => handleInputChange('etoro_account_id', e.target.value)}
              placeholder="Enter your eToro account ID"
              className="w-full px-3 py-2 bg-surface-800 border border-surface-700 rounded-lg text-white placeholder-surface-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>
        </div>
      </div>

      {/* Telegram Settings */}
      <div className="bg-surface-900 rounded-xl border border-surface-800 p-6">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 rounded-lg bg-blue-500/20 flex items-center justify-center">
            <MessageSquare size={20} className="text-blue-400" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-white">Telegram Bot</h2>
            <p className="text-surface-400 text-sm">Configure Telegram notifications</p>
          </div>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-surface-300 mb-2">
              Bot Token
            </label>
            <input
              type="password"
              value={settings.telegram_bot_token}
              onChange={(e) => handleInputChange('telegram_bot_token', e.target.value)}
              placeholder="Enter your Telegram bot token"
              className="w-full px-3 py-2 bg-surface-800 border border-surface-700 rounded-lg text-white placeholder-surface-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-surface-300 mb-2">
              Chat ID
            </label>
            <input
              type="text"
              value={settings.telegram_chat_id}
              onChange={(e) => handleInputChange('telegram_chat_id', e.target.value)}
              placeholder="Enter your Telegram chat ID"
              className="w-full px-3 py-2 bg-surface-800 border border-surface-700 rounded-lg text-white placeholder-surface-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
            />
          </div>
        </div>
      </div>

      {/* Trading Mode */}
      <div className="bg-surface-900 rounded-xl border border-surface-800 p-6">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 rounded-lg bg-amber-500/20 flex items-center justify-center">
            <User size={20} className="text-amber-400" />
          </div>
          <div>
            <h2 className="text-lg font-semibold text-white">Trading Mode</h2>
            <p className="text-surface-400 text-sm">Switch between simulation and live trading</p>
          </div>
        </div>

        <div className="flex items-center justify-between">
          <div>
            <p className="text-white font-medium">Simulation Mode</p>
            <p className="text-surface-400 text-sm">
              {settings.is_simulation
                ? 'Currently in simulation mode. No real trades will be executed.'
                : 'Currently in live trading mode. Real trades will be executed.'
              }
            </p>
          </div>
          <label className="relative inline-flex items-center cursor-pointer">
            <input
              type="checkbox"
              checked={settings.is_simulation}
              onChange={(e) => handleInputChange('is_simulation', e.target.checked)}
              className="sr-only peer"
            />
            <div className="w-11 h-6 bg-surface-700 peer-focus:outline-none peer-focus:ring-4 peer-focus:ring-blue-500/20 rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-blue-500"></div>
          </label>
        </div>
      </div>

      {/* Save Button */}
      <div className="flex justify-end">
        <button
          onClick={handleSave}
          disabled={saving}
          className="px-6 py-2 bg-blue-500 hover:bg-blue-600 disabled:bg-blue-500/50 disabled:cursor-not-allowed text-white rounded-lg font-medium flex items-center gap-2 transition-colors"
        >
          <Save size={18} />
          {saving ? 'Saving...' : 'Save Settings'}
        </button>
      </div>
    </div>
  )
}