/**
 * API Service
 * All backend HTTP calls go through this module.
 * Centralizes error handling and base URL configuration.
 */

import axios from 'axios'

export const API_URL = import.meta.env.VITE_API_URL ||
  (import.meta.env.MODE === 'production'
    ? 'https://smartetoro2.onrender.com'
    : 'http://localhost:8000')

const api = axios.create({
  baseURL: API_URL,
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
})

// Global error logging
api.interceptors.response.use(
  res => res,
  err => {
    console.error(`API Error [${err.config?.url}]:`, err.message)
    return Promise.reject(err)
  }
)

// ── Portfolio ──────────────────────────────────
export const portfolioAPI = {
  get:         (id) =>    api.get(`/api/portfolios/${id}`).then(r => r.data),
  update:      (id, d) => api.patch(`/api/portfolios/${id}`, d).then(r => r.data),
  health:      (id) =>    api.get(`/api/portfolios/${id}/health`).then(r => r.data),
  performance: (id, days=30) => api.get(`/api/portfolios/${id}/performance?days=${days}`).then(r => r.data),
}

// ── Traders ────────────────────────────────────
export const tradersAPI = {
  list:     (pid) =>       api.get(`/api/portfolios/${pid}/traders`).then(r => r.data),
  add:      (pid, d) =>    api.post(`/api/portfolios/${pid}/traders`, d).then(r => r.data),
  update:   (tid, d) =>    api.patch(`/api/traders/${tid}`, d).then(r => r.data),
  analyze:  (tid) =>       api.get(`/api/traders/${tid}/analytics`).then(r => r.data),
}

// ── AI Analysis ────────────────────────────────
export const aiAPI = {
  analyze:         (d) =>   api.post('/api/ai/analyze', d).then(r => r.data),
  recommendations: (pid, limit=10) =>
                            api.get(`/api/portfolios/${pid}/recommendations?limit=${limit}`).then(r => r.data),
}

// ── Risk ───────────────────────────────────────
export const riskAPI = {
  check:          (pid) =>    api.get(`/api/portfolios/${pid}/risk/check`).then(r => r.data),
  getSettings:    (pid) =>    api.get(`/api/portfolios/${pid}/risk/settings`).then(r => r.data),
  updateSettings: (pid, d) => api.patch(`/api/portfolios/${pid}/risk/settings`, d).then(r => r.data),
}

// ── Automation ────────────────────────────────
export const automationAPI = {
  listRules:    (pid) =>        api.get(`/api/portfolios/${pid}/automation/rules`).then(r => r.data),
  createRule:   (pid, d) =>     api.post(`/api/portfolios/${pid}/automation/rules`, d).then(r => r.data),
  toggleRule:   (pid, rid) =>   api.post(`/api/portfolios/${pid}/automation/rules/${rid}/toggle`).then(r => r.data),
  emergencyStop:(pid) =>        api.post(`/api/portfolios/${pid}/automation/emergency-stop`).then(r => r.data),
  getLogs:      (pid, limit=50) => api.get(`/api/portfolios/${pid}/automation/logs?limit=${limit}`).then(r => r.data),
  reverseAction:(lid, pid) =>   api.post(`/api/automation/logs/${lid}/reverse?portfolio_id=${pid}`).then(r => r.data),
}

// ── Alerts ────────────────────────────────────
export const alertsAPI = {
  list:   (pid, unread=false) =>
          api.get(`/api/portfolios/${pid}/alerts?unread_only=${unread}&limit=50`).then(r => r.data),
  markRead: (aid) => api.post(`/api/alerts/${aid}/read`).then(r => r.data),
}

export default api
