/**
 * CameraView — live video of a camera with detection boxes, state, FPS and traffic-analysis counters.
 *
 * The picture is an MJPEG stream from the backend (boxes are drawn server side, so what you see is exactly what
 * the analysis used). Works the same for a simulation camera, a video file, a USB or a network camera.
 * A camera that is disconnected / has no signal shows a labelled placeholder — the page never breaks.
 */
import { useState } from 'react'
import api from '../api/client'
import useVision from '../hooks/useVision'

const STATE_COLOR = {
  connected: '#68d391', connecting: '#f6e05e', no_signal: '#fc8181', error: '#fc8181', disconnected: '#a0aec0',
}
const STATE_LABEL = {
  connected: 'подключена', connecting: 'подключение…', no_signal: 'нет сигнала', error: 'ошибка', disconnected: 'отключена',
}
const CLASS_COLOR = {
  car: '#3b82f6', truck: '#f97316', bus: '#22c55e', tram: '#a855f7', emergency: '#ef4444',
  person: '#facc15', motorcycle: '#06b6d4', bicycle: '#84cc16',
}

export const streamUrl = (id, zones) =>
  `${api.defaults.baseURL}/api/vision/cameras/${id}/stream?overlay=true&zones=${zones}`

export default function CameraView({ compact = false }) {
  const { vision, offline } = useVision()
  const [selected, setSelected] = useState(null)
  const [zones, setZones] = useState(false)
  const [busy, setBusy] = useState(false)

  const cams = vision?.cameras ?? []
  const cam = cams.find(c => c.id === selected) ?? cams[0]
  const analysis = vision?.analysis

  const toggle = async () => {
    if (!cam || busy) return
    setBusy(true)
    try {
      await api.post(`/api/vision/cameras/${cam.id}/${cam.enabled ? 'disconnect' : 'connect'}`)
    } finally {
      setBusy(false)
    }
  }

  const box = { background: '#1a1d27', border: '1px solid #2d3748', borderRadius: 10, padding: compact ? 10 : 16 }
  const title = { fontWeight: 700, fontSize: compact ? 12 : 14, color: '#e2e8f0' }

  if (offline && !vision) {
    return <div style={box}><div style={title}>📷 Камера</div>
      <div style={{ color: '#fc8181', fontSize: 12, marginTop: 8 }}>Backend недоступен (порт 8000)</div></div>
  }
  if (!cam) {
    return <div style={box}><div style={title}>📷 Камера</div>
      <div style={{ color: '#718096', fontSize: 12, marginTop: 8 }}>
        Камеры не настроены (config/cameras.yaml). Система работает и без камеры.</div></div>
  }

  const color = STATE_COLOR[cam.state] || '#a0aec0'
  const counts = Object.entries(analysis?.counts ?? {})
  const det = cam.detector || {}

  return (
    <div style={box}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span style={title}>📷 {cam.name || cam.id}</span>
        <span style={{ fontSize: 11, color, border: `1px solid ${color}55`, background: color + '22',
                       borderRadius: 4, padding: '1px 7px', fontWeight: 600 }}>
          {STATE_LABEL[cam.state] || cam.state}
        </span>
        <span style={{ fontSize: 11, color: '#718096' }}>{cam.source} · {cam.fps.toFixed(1)} FPS</span>
        {cams.length > 1 && (
          <select value={cam.id} onChange={e => setSelected(e.target.value)}
                  style={{ marginLeft: 'auto', background: '#131722', color: '#e2e8f0', border: '1px solid #2d3748', fontSize: 11 }}>
            {cams.map(c => <option key={c.id} value={c.id}>{c.id}</option>)}
          </select>
        )}
      </div>

      {offline && (
        <div style={{ color: '#fc8181', fontSize: 11, marginTop: 6 }}>Backend недоступен — данные камеры устарели</div>
      )}

      <div style={{ position: 'relative', marginTop: 8, background: '#000', borderRadius: 6, overflow: 'hidden',
                    aspectRatio: `${cam.width} / ${cam.height}` }}>
        <img key={`${cam.id}-${zones}`} src={streamUrl(cam.id, zones)} alt={`camera ${cam.id}`}
             style={{ width: '100%', height: '100%', objectFit: 'contain', display: 'block' }} />
        {!vision?.healthy && (
          <div style={{ position: 'absolute', left: 0, right: 0, bottom: 0, background: 'rgba(116,42,42,0.9)',
                        color: '#fed7d7', fontSize: 11, padding: '4px 8px' }}>
            ⚠ {vision?.reason} — светофоры в режиме FAILSAFE
          </div>
        )}
      </div>

      <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap', alignItems: 'center' }}>
        <button onClick={toggle} disabled={busy}
                style={{ padding: '4px 10px', borderRadius: 5, fontSize: 11, cursor: 'pointer', border: 'none', fontWeight: 600,
                         background: cam.enabled ? '#742a2a' : '#276749', color: '#fff' }}>
          {cam.enabled ? '⏏ Отключить камеру' : '🔌 Подключить камеру'}
        </button>
        <label style={{ fontSize: 11, color: '#a0aec0', display: 'flex', alignItems: 'center', gap: 4 }}>
          <input type="checkbox" checked={zones} onChange={e => setZones(e.target.checked)} /> зоны
        </label>
        <span style={{ fontSize: 11, color: det.state === 'ok' ? '#68d391' : '#fc8181', marginLeft: 'auto' }}>
          детектор {det.name}: {det.state}
        </span>
      </div>
      {det.error && <div style={{ color: '#fc8181', fontSize: 11, marginTop: 4 }}>{det.error}</div>}
      {cam.error && <div style={{ color: '#fc8181', fontSize: 11, marginTop: 4 }}>{cam.error}</div>}

      <div style={{ display: 'flex', gap: 6, marginTop: 8, flexWrap: 'wrap' }}>
        {counts.length === 0 && <span style={{ fontSize: 11, color: '#718096' }}>объектов нет</span>}
        {counts.map(([cls, n]) => (
          <span key={cls} style={{ fontSize: 11, padding: '1px 7px', borderRadius: 4, color: '#e2e8f0',
                                   background: (CLASS_COLOR[cls] || '#718096') + '55',
                                   border: `1px solid ${CLASS_COLOR[cls] || '#718096'}` }}>
            {cls}: {n}
          </span>
        ))}
      </div>

      {analysis && !compact && (
        <div style={{ display: 'flex', gap: 14, marginTop: 8, fontSize: 11, color: '#a0aec0', flexWrap: 'wrap' }}>
          <span>ожидают: <b style={{ color: '#e2e8f0' }}>{analysis.waiting_vehicles}</b></span>
          <span>плотность: <b style={{ color: '#e2e8f0' }}>{Math.round(analysis.density * 100)}%</b></span>
          <span>поток: <b style={{ color: '#e2e8f0' }}>{Math.round(analysis.vehicles_per_hour)}</b> авт/ч</span>
          <span>пешеходов ждёт: <b style={{ color: '#e2e8f0' }}>{analysis.pedestrians_waiting}</b></span>
          {analysis.ped_priority && <span style={{ color: '#f6e05e' }}>приоритет пешеходной фазы</span>}
        </div>
      )}
    </div>
  )
}
