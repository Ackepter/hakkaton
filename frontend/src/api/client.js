import axios from 'axios'

const api = axios.create({
  baseURL: `http://${window.location.hostname}:8000`,
  timeout: 5000,
})

export const intersectionApi = {
  get: () => api.get('/api/intersection'),
  save: (config) => api.post('/api/intersection', config),
  clear: () => api.delete('/api/intersection'),
}

export const lightsApi = {
  getAll: () => api.get('/api/lights'),
  manualControl: (lightId, state) =>
    api.post('/api/lights/manual', { light_id: lightId, state }),
  updatePhases: (lightId, phases) =>
    api.put('/api/lights/phases', { light_id: lightId, phases }),
}

export const controlApi = {
  setMode: (mode) => api.post('/api/control/mode', { mode }),
  triggerFailsafe: (reason) =>
    api.post(`/api/control/failsafe?reason=${encodeURIComponent(reason)}`),
  recover: () => api.post('/api/control/recover'),
  simulationControl: (action, speed) =>
    api.post('/api/control/simulation', { action, speed }),
  updatePriorities: (priorities) =>
    api.post('/api/control/priorities', { direction_priorities: priorities }),
  getStatus: () => api.get('/api/control/status'),
}

export const metricsApi = {
  get: () => api.get('/api/metrics'),
  getHistory: (seconds) => api.get(`/api/metrics/history?seconds=${seconds}`),
  getChart: (metric, seconds) =>
    api.get(`/api/metrics/chart/${metric}?seconds=${seconds}`),
}

export default api
