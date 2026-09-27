import axios from 'axios'
import backend from '../api/client'

export const SI_URL = `http://${window.location.hostname}:8001`
const si = axios.create({ baseURL: SI_URL, timeout: 6000 })

/** Errors from the simulation service as a list of readable strings. */
export function errorList(e) {
  const d = e?.response?.data?.detail
  if (Array.isArray(d)) return d.map(x => (typeof x === 'string' ? x : `${(x.loc || []).slice(1).join('.')}: ${x.msg}`))
  if (typeof d === 'string') return [d]
  if (e?.code === 'ECONNABORTED' || !e?.response) return ['Smart Intersection service is not reachable (port 8001)']
  return [e.message || 'unknown error']
}

export const layoutApi = {
  get: () => si.get('/layout').then(r => r.data),
  apply: (layout) => si.put('/layout', layout).then(r => r.data),
  validate: (layout) => si.post('/layout/validate', layout).then(r => r.data),
  presets: () => si.get('/layout/presets').then(r => r.data),
  junctionTypes: () => si.get('/layout/junction-types').then(r => r.data.types),
  list: () => si.get('/layouts').then(r => r.data),
  save: (layout) => si.post('/layouts', layout).then(r => r.data),
  load: (name) => si.get(`/layouts/${encodeURIComponent(name)}`).then(r => r.data),
  remove: (name) => si.delete(`/layouts/${encodeURIComponent(name)}`).then(r => r.data),
  spawn: (body) => si.post('/simulation/spawn', body).then(r => r.data),
  start: () => si.post('/simulation/start'),
  pause: () => si.post('/simulation/pause'),
  syncCameras: () => backend.post('/api/vision/sync-layout').then(r => r.data),
}
