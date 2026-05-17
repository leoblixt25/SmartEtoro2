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

api.interceptors.response.use(
  res => res,
  err => {
    console.error(`API Error [${err.config?.url}]:`, err.message)
    return Promise.reject(err)
  }
)

export const portfolioAPI = {
  get:       (id) =>    api.get(`/api/portfolios/${id}`).then(r => r.data),
  update:    (id, d) => api.patch(`/api/portfolios/${id}`, d).then(r => r.data),
  overview:  (id) =>    api.get(`/api/portfolios/${id}/overview`).then(r => r.data),
  dashboard: (id) =>    api.get(`/api/portfolios/${id}/dashboard`).then(r => r.data),
  discovery: (id) =>    api.get(`/api/portfolios/${id}/discovery`).then(r => r.data),
}

export const tradersAPI = {
  list:     (pid) =>       api.get(`/api/portfolios/${pid}/traders`).then(r => r.data),
  add:      (pid, d) =>    api.post(`/api/portfolios/${pid}/traders`, d).then(r => r.data),
  update:   (tid, d) =>    api.patch(`/api/traders/${tid}`, d).then(r => r.data),
  active:   (pid) =>       api.get(`/api/portfolios/${pid}/active-traders`).then(r => r.data),
}

export const alertsAPI = {
  list:     (pid, unread=false) =>
            api.get(`/api/portfolios/${pid}/alerts?unread_only=${unread}&limit=50`).then(r => r.data),
  summary:  (pid) =>
            api.get(`/api/portfolios/${pid}/alerts/summary`).then(r => r.data),
  markRead: (aid) => api.post(`/api/alerts/${aid}/read`).then(r => r.data),
  markAllRead: (pid) => api.post(`/api/portfolios/${pid}/alerts/read-all`).then(r => r.data),
}

export default api
