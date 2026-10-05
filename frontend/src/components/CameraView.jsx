/**
 * CameraView — live video of a camera with detection boxes, state, FPS and traffic-analysis counters.
 *
 * The picture is an MJPEG stream from the backend (boxes are drawn server side, so what you see is exactly what
 * the analysis used). Works the same for a simulation camera, a video file, a USB or a network camera.
 * A camera that is disconnected / has no signal shows a labelled placeholder — the page never breaks.
 */
import { useEffect, useState } from 'react'
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
const PHASE_COLOR = { GREEN: '#68d391', BLINK: '#68d391', YELLOW: '#f6e05e', RED: '#fc8181' }
const PHASE_LABEL = { GREEN: '🟢 зелёный', BLINK: '🟢 мигает', YELLOW: '🟡 жёлтый', RED: '🔴 красный' }

export const streamUrl = (id, zones) =>
  `${api.defaults.baseURL}/api/vision/cameras/${id}/stream?overlay=true&zones=${zones}`

export default function CameraView({ compact = false }) {
  const { vision, offline } = useVision()
  const [selected, setSelected] = useState(null)
  const [zones, setZones] = useState(false)
  const [busy, setBusy] = useState(false)
  const [usbDevices, setUsbDevices] = useState(null)
  const [usbLoading, setUsbLoading] = useState(false)
  const [testMode, setTestMode] = useState(null)
  const [testIp, setTestIp] = useState('192.168.1.200')
  const [testPort, setTestPort] = useState('9000')
  const [testBusy, setTestBusy] = useState(false)

  const cams = vision?.cameras ?? []
  const cam = cams.find(c => c.id === selected) ?? cams[0]
  const analysis = vision?.analysis

  useEffect(() => {
    let alive = true
    const poll = async () => {
      try {
        const r = await api.get('/api/vision/test-mode')
        if (alive) setTestMode(r.data)
      } catch { /* backend offline - useVision already reports this */ }
    }
    poll()
    const t = setInterval(poll, 1000)
    return () => { alive = false; clearInterval(t) }
  }, [])

  const toggleTestMode = async () => {
    if (!cam || testBusy) return
    setTestBusy(true)
    try {
      if (testMode?.active) {
        await api.post('/api/vision/test-mode/stop')
      } else {
        const port = parseInt(testPort, 10) || 9000
        await api.post('/api/vision/test-mode/start', { camera_id: cam.id, ip: testIp, port })
      }
      const r = await api.get('/api/vision/test-mode')
      setTestMode(r.data)
    } finally {
      setTestBusy(false)
    }
  }

  const toggle = async () => {
    if (!cam || busy) return
    setBusy(true)
    try {
      await api.post(`/api/vision/cameras/${cam.id}/${cam.enabled ? 'disconnect' : 'connect'}`)
    } finally {
      setBusy(false)
    }
  }

  const loadUsbDevices = async () => {
    if (usbLoading) return
    setUsbLoading(true)
    try {
      const r = await api.get('/api/vision/discover')
      setUsbDevices(r.data.usb ?? [])
    } catch {
      setUsbDevices([])
    } finally {
      setUsbLoading(false)
    }
  }

  const selectDevice = async (index) => {
    if (!cam || busy) return
    setBusy(true)
    try {
      await api.post(`/api/vision/cameras/${cam.id}/device`, { uri: String(index) })
    } finally {
      setBusy(false)
    }
  }

  const boxCls = `rounded-lg border border-border bg-card ${compact ? 'p-2.5' : 'p-4'}`
  const titleCls = `font-bold ${compact ? 'text-xs' : 'text-sm'}`

  if (offline && !vision) {
    return <div className={boxCls}><div className={titleCls}>📷 Камера</div>
      <div className="mt-2 text-xs text-destructive">Backend недоступен (порт 8000)</div></div>
  }
  if (!cam) {
    return <div className={boxCls}><div className={titleCls}>📷 Камера</div>
      <div className="mt-2 text-xs text-muted-foreground">
        Камеры не настроены (config/cameras.yaml). Система работает и без камеры.</div></div>
  }

  const color = STATE_COLOR[cam.state] || '#a0aec0'
  const counts = Object.entries(analysis?.counts ?? {})
  const det = cam.detector || {}

  return (
    <div className={boxCls}>
      <div className="flex flex-wrap items-center gap-2">
        <span className={titleCls}>📷 {cam.name || cam.id}</span>
        <span className="rounded px-1.5 py-0.5 text-[11px] font-semibold"
              style={{ color, border: `1px solid ${color}55`, background: color + '22' }}>
          {STATE_LABEL[cam.state] || cam.state}
        </span>
        <span className="text-[11px] text-muted-foreground">{cam.source} · {cam.fps.toFixed(1)} FPS</span>
        {cams.length > 1 && (
          <select value={cam.id} onChange={e => setSelected(e.target.value)}
                  className="ml-auto rounded border border-input bg-background text-[11px]">
            {cams.map(c => <option key={c.id} value={c.id}>{c.id}</option>)}
          </select>
        )}
      </div>

      {offline && (
        <div className="mt-1.5 text-[11px] text-destructive">Backend недоступен — данные камеры устарели</div>
      )}

      <div className="relative mt-2 overflow-hidden rounded-md bg-black" style={{ aspectRatio: `${cam.width} / ${cam.height}` }}>
        <img key={`${cam.id}-${zones}`} src={streamUrl(cam.id, zones)} alt={`camera ${cam.id}`}
             className="block h-full w-full object-contain" />
        {!vision?.healthy && (
          <div className="absolute bottom-0 left-0 right-0 bg-destructive/90 px-2 py-1 text-[11px] text-destructive-foreground">
            ⚠ {vision?.reason} — светофоры в режиме FAILSAFE
          </div>
        )}
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-1.5">
        <button onClick={toggle} disabled={busy}
                className="rounded px-2.5 py-1 text-[11px] font-semibold text-white"
                style={{ background: cam.enabled ? '#742a2a' : '#276749' }}>
          {cam.enabled ? '⏏ Отключить камеру' : '🔌 Подключить камеру'}
        </button>
        <label className="flex items-center gap-1 text-[11px] text-muted-foreground">
          <input type="checkbox" checked={zones} onChange={e => setZones(e.target.checked)} /> зоны
        </label>
        <span className="ml-auto text-[11px]" style={{ color: det.state === 'ok' ? '#68d391' : '#fc8181' }}>
          детектор {det.name}: {det.state}
        </span>
      </div>
      {det.error && <div className="mt-1 text-[11px] text-destructive">{det.error}</div>}
      {cam.error && <div className="mt-1 text-[11px] text-destructive">{cam.error}</div>}

      {cam.source === 'usb' && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-muted-foreground">USB устройство:</span>
          <button onClick={loadUsbDevices} disabled={usbLoading}
                  className="rounded border border-input px-2 py-0.5 text-[11px]">
            {usbLoading ? '…' : '🔍 обновить список'}
          </button>
          {usbDevices === null ? null : usbDevices.length === 0 ? (
            <span className="text-[11px] text-destructive">не найдено</span>
          ) : (
            <select value={cam.uri} disabled={busy} onChange={e => selectDevice(e.target.value)}
                    className="rounded border border-input bg-background text-[11px]">
              {usbDevices.map(d => (
                <option key={d.index} value={d.index}>#{d.index} ({d.width}x{d.height})</option>
              ))}
            </select>
          )}
        </div>
      )}

      {cam.source === 'usb' && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5 rounded border border-input p-1.5">
          <button onClick={toggleTestMode} disabled={testBusy}
                  className="rounded px-2.5 py-1 text-[11px] font-semibold text-white"
                  style={{ background: testMode?.active && testMode.camera_id === cam.id ? '#742a2a' : '#2c5282' }}>
            {testMode?.active && testMode.camera_id === cam.id ? '⏹ Выключить тестовый режим' : '🚦 Тестовый режим'}
          </button>
          <input value={testIp} onChange={e => setTestIp(e.target.value)}
                 disabled={testMode?.active} placeholder="IP светофора"
                 className="w-28 rounded border border-input bg-background px-1.5 py-0.5 text-[11px]" />
          <span className="text-[11px] text-muted-foreground">:</span>
          <input value={testPort} onChange={e => setTestPort(e.target.value)}
                 disabled={testMode?.active} placeholder="9000"
                 className="w-14 rounded border border-input bg-background px-1.5 py-0.5 text-[11px]" />
          {testMode?.active && testMode.camera_id === cam.id && (
            <span className="text-[11px] font-semibold" style={{ color: PHASE_COLOR[testMode.phase] || '#a0aec0' }}>
              {PHASE_LABEL[testMode.phase] || testMode.phase} · {testMode.person_detected ? 'person есть' : 'person нет'}
              {' '}→ {testMode.ip}:{testMode.port}
            </span>
          )}
          {testMode?.active && testMode.camera_id !== cam.id && (
            <span className="text-[11px] text-muted-foreground">запущен на {testMode.camera_id}</span>
          )}
        </div>
      )}

      <div className="mt-2 flex flex-wrap gap-1.5">
        {counts.length === 0 && <span className="text-[11px] text-muted-foreground">объектов нет</span>}
        {counts.map(([cls, n]) => (
          <span key={cls} className="rounded px-1.5 py-0.5 text-[11px]"
                style={{ background: (CLASS_COLOR[cls] || '#718096') + '55', border: `1px solid ${CLASS_COLOR[cls] || '#718096'}` }}>
            {cls}: {n}
          </span>
        ))}
      </div>

      {analysis && !compact && (
        <div className="mt-2 flex flex-wrap gap-3.5 text-[11px] text-muted-foreground">
          <span>ожидают: <b className="text-foreground">{analysis.waiting_vehicles}</b></span>
          <span>плотность: <b className="text-foreground">{Math.round(analysis.density * 100)}%</b></span>
          <span>поток: <b className="text-foreground">{Math.round(analysis.vehicles_per_hour)}</b> авт/ч</span>
          <span>пешеходов ждёт: <b className="text-foreground">{analysis.pedestrians_waiting}</b></span>
          {analysis.ped_priority && <span className="text-yellow-400">приоритет пешеходной фазы</span>}
        </div>
      )}
    </div>
  )
}
