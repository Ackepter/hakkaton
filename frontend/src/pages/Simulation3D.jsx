/**
 * Simulation3D — the city: watch the simulation (Play) or build it (Build).
 *
 * Play:  live traffic, metrics, camera view, scenario controls, interactive spawn tools.
 * Build: place / move / delete objects on the 3D map, edit roads, the signal program and traffic, save / load cities.
 *        Edits go to a local draft (with undo); "Apply" sends it to the simulation service, which validates it and
 *        rebuilds the world.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import axios from 'axios'
import IntersectionScene from '../components/scene/IntersectionScene'
import SimControls from '../components/scene/SimControls'
import CameraView from '../components/CameraView'
import BuilderPanel from '../components/builder/BuilderPanel'
import Toolbar from '../components/builder/Toolbar'
import useVision from '../hooks/useVision'
import useLayoutDraft from '../builder/useLayoutDraft'
import { errorList, layoutApi, SI_URL } from '../builder/api'
import { ARMS } from '../builder/geometry'

const WS_URL = `ws://${window.location.hostname}:8001/ws/state`
const API_URL = `${SI_URL}/simulation/state`
const LIGHT_COLORS = { RED: '#ef4444', YELLOW: '#fbbf24', GREEN: '#22c55e' }
const SECTION_GLYPH = { left: '↰', right: '↱', uturn: '↩' }
const NAV_H = 56

const FALLBACK_LAYOUT = {
  version: 1, name: 'Crossroads', junction: 'signal', scenery: [], cameras: [],
  arms: Object.fromEntries(ARMS.map(a => [a, { enabled: true, length_m: 80, lane_type: 'mixed', lanes_in: 1, lanes_out: 1, turns: null,
                                                speed_limit_mps: 13.9, crossing: true, weight: 1, light_ip: null, light_port: 9000 }])),
  signal: { mode: 'adaptive', base_green: 30, min_green: 8, max_green: 60, yellow: 3, all_red: 3, program: [] },
  traffic: { spawn_rate: 12, ped_spawn_rate: 5, type_probs: { car: 0.75, truck: 0.1, bus: 0.1, tram: 0.04, emergency: 0.01 } },
}

const HINTS = {
  select: 'Click an object to select it, drag to move it. Right mouse button rotates the view, wheel zooms.',
  delete: 'Click an object to delete it.',
  camera: 'Click to place a camera; select it to set height, field of view and aim. The dashed area is what it sees.',
}

export default function Simulation3D() {
  const [simState, setSimState] = useState(null)
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState(null)
  const wsRef = useRef(null)
  const pollRef = useRef(null)
  const { vision } = useVision()
  const camera = vision?.cameras?.[0] ?? null

  const [serverLayout, setServerLayout] = useState(FALLBACK_LAYOUT)
  const [mode, setMode] = useState('play')
  const [tool, setTool] = useState(null)
  const [selection, setSelection] = useState(null)
  const [rotation, setRotation] = useState(0)
  const [tab, setTab] = useState('objects')
  const [errors, setErrors] = useState([])
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [saved, setSaved] = useState([])
  const [presets, setPresets] = useState({})
  const [junctionTypes, setJunctionTypes] = useState([])
  const d = useLayoutDraft()
  const { draft } = d

  const say = useCallback((m) => { setMessage(m); setTimeout(() => setMessage(cur => (cur === m ? '' : cur)), 4000) }, [])

  // ---- live state (WebSocket, HTTP polling as fallback)
  useEffect(() => {
    let alive = true
    function startPolling() {
      if (pollRef.current) return
      pollRef.current = setInterval(async () => {
        try {
          const r = await axios.get(API_URL)
          if (alive) { setSimState(r.data); setConnected(true); setError(null) }
        } catch {
          if (alive) { setConnected(false); setError('SI service offline — start it with start.bat') }
        }
      }, 500)
    }
    function connectWS() {
      if (!alive) return
      try {
        const ws = new WebSocket(WS_URL)
        wsRef.current = ws
        ws.onopen = () => { if (alive) { setConnected(true); setError(null) }
                            if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null } }
        ws.onmessage = e => { try { if (alive) setSimState(JSON.parse(e.data)) } catch {} }
        ws.onclose = () => { if (alive) { setConnected(false); startPolling(); setTimeout(connectWS, 3000) } }
        ws.onerror = () => ws.close()
      } catch { startPolling() }
    }
    connectWS()
    return () => { alive = false; wsRef.current?.close(); if (pollRef.current) clearInterval(pollRef.current) }
  }, [])

  // ---- layout: load once, keep the draft in step
  const loadFromServer = useCallback(async () => {
    try {
      const l = await layoutApi.get()
      setServerLayout(l)
      d.reset(l)
      return l
    } catch (e) {
      setErrors(errorList(e))
      d.reset(FALLBACK_LAYOUT)
      return null
    }
  }, [d.reset])

  useEffect(() => { loadFromServer().then(() => layoutApi.syncCameras().catch(() => {})) }, [])   // eslint-disable-line

  const refreshCities = useCallback(async () => {
    try { setSaved((await layoutApi.list()).saved) } catch {}
    try { setPresets(await layoutApi.presets()) } catch {}
    try { setJunctionTypes(await layoutApi.junctionTypes()) } catch {}
  }, [])
  useEffect(() => { if (mode === 'build') refreshCities() }, [mode, refreshCities])

  // ---- live validation of the draft while building
  useEffect(() => {
    if (mode !== 'build' || !draft) return undefined
    const t = setTimeout(async () => {
      try { setErrors((await layoutApi.validate(draft)).errors) } catch (e) { setErrors(errorList(e)) }
    }, 400)
    return () => clearTimeout(t)
  }, [draft, mode])

  const apply = useCallback(async () => {
    if (!draft) return false
    setBusy(true)
    try {
      const l = await layoutApi.apply(draft)
      setServerLayout(l)
      d.reset(l)
      setErrors([])
      layoutApi.syncCameras().catch(() => {})
      say('Applied — the simulation was rebuilt')
      return true
    } catch (e) {
      setErrors(errorList(e))
      return false
    } finally {
      setBusy(false)
    }
  }, [draft, d.reset, say])

  const play = useCallback(async () => {
    if (d.dirty && !(await apply())) return
    try { await layoutApi.start() } catch {}
    setMode('play'); setTool(null); setSelection(null)
  }, [d.dirty, apply])

  const edit = useCallback(async () => {
    try { await layoutApi.pause() } catch {}
    d.reset(serverLayout)
    setMode('build'); setTool('select'); setSelection(null); setErrors([])
  }, [serverLayout, d.reset])

  // ---- cities: save / load / presets / files
  const save = async () => {
    try { await layoutApi.save(draft); await refreshCities(); say(`Saved "${draft.name}"`); setErrors([]) }
    catch (e) { setErrors(errorList(e)) }
  }
  const useLayout = (l, what) => { d.reset(l, true); setSelection(null); setTab('objects'); say(`${what} loaded — press Apply`) }
  const loadSaved = async (name) => { try { useLayout(await layoutApi.load(name), `"${name}"`) } catch (e) { setErrors(errorList(e)) } }
  const deleteSaved = async (name) => { try { await layoutApi.remove(name); await refreshCities() } catch (e) { setErrors(errorList(e)) } }
  const download = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(draft, null, 2)], { type: 'application/json' }))
    const a = document.createElement('a')
    a.href = url; a.download = `${draft.name}.json`; a.click()
    URL.revokeObjectURL(url)
  }
  const upload = async (file) => {
    try {
      const l = JSON.parse(await file.text())
      const v = await layoutApi.validate(l)
      if (!v.valid) { setErrors(v.errors); return }
      useLayout(l, file.name)
    } catch (e) { setErrors(e instanceof SyntaxError ? ['That file is not valid JSON'] : errorList(e)) }
  }

  const onSpawn = async (body) => {
    try { await layoutApi.spawn(body) } catch (e) { say(errorList(e)[0]) }
  }

  // ---- keyboard shortcuts (build mode)
  useEffect(() => {
    if (mode !== 'build') return undefined
    const onKey = (e) => {
      if (/^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return
      const k = e.key.toLowerCase()
      if ((e.ctrlKey || e.metaKey) && k === 'z') { e.preventDefault(); e.shiftKey ? d.redo() : d.undo() }
      else if ((e.ctrlKey || e.metaKey) && k === 'y') { e.preventDefault(); d.redo() }
      else if ((k === 'delete' || k === 'backspace') && selection) { d.actions.remove(selection.kind, selection.id); setSelection(null) }
      else if (k === 'escape') { setTool('select'); setSelection(null) }
      else if (k === 'r') setRotation(r => (r + (e.shiftKey ? 90 : 15)) % 360)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [mode, selection, d])

  const cameraStatus = (id) => {
    const c = vision?.cameras?.find(x => x.id === id)
    return c ? c.healthy : true
  }

  const build = mode === 'build'
  const layout = build && draft ? draft : serverLayout
  const vehicles = simState?.vehicles ?? []
  const pedestrians = simState?.pedestrians ?? []
  const lights = simState?.lights ?? []
  const pedestrianLights = simState?.pedestrian_lights ?? []
  const cameraPriority = simState?.camera_priority
  const metrics = simState?.metrics ?? null
  const status = simState?.status ?? 'stopped'
  const simTime = simState?.sim_time ?? 0
  const hint = build ? (tool?.startsWith('place:') ? 'Click to place. Green ring = allowed. R rotates.' : HINTS[tool])
    : tool?.startsWith('spawn:') ? 'Click next to a road to add it there. Click the tool again to stop.' : null

  return (
    <div style={{ display: 'flex', height: `calc(100vh - ${NAV_H}px)`, overflow: 'hidden', background: '#0f172a' }}>
      <aside style={{ width: build ? 330 : 200, flexShrink: 0, overflowY: 'auto', background: '#111827',
                      borderRight: '1px solid #1e293b', padding: 12 }}>
        {build && draft ? (
          <BuilderPanel draft={draft} dirty={d.dirty} actions={d.actions} undo={d.undo} redo={d.redo}
                        canUndo={d.canUndo} canRedo={d.canRedo} tool={tool} setTool={setTool} rotation={rotation}
                        setRotation={setRotation} selection={selection} clear={() => setSelection(null)}
                        errors={errors} busy={busy} message={message} onApply={apply} onPlay={play} tab={tab} setTab={setTab}
                        saved={saved} presets={presets} junctionTypes={junctionTypes} onSave={save} onLoadSaved={loadSaved}
                        onLoadPreset={(n) => useLayout(presets[n], `"${n}"`)} onDeleteSaved={deleteSaved}
                        onDownload={download} onUpload={upload} />
        ) : (
          <>
            <button onClick={edit} data-testid="edit-city"
                    style={{ width: '100%', marginBottom: 12, background: '#7c3aed', color: '#fff', border: 'none', borderRadius: 6,
                             padding: '8px 10px', fontSize: 13, fontWeight: 700, cursor: 'pointer' }}>🏗 Build mode</button>
            <SimControls simStatus={status} metrics={metrics} cameraFailure={!!simState?.camera_failure}
                         failsafeReason={simState?.failsafe_reason ?? null} />
            {message && <div style={{ color: '#86efac', fontSize: 11, marginTop: 8 }}>{message}</div>}
          </>
        )}
      </aside>

      <main style={{ flex: 1, position: 'relative', minWidth: 0, height: '100%' }}>
        <IntersectionScene layout={layout} vehicles={vehicles} pedestrians={pedestrians} lights={lights}
                           pedestrianLights={pedestrianLights}
                           cameraStatus={cameraStatus} mode={mode} tool={tool} selection={selection}
                           setSelection={setSelection} actions={draft ? d.actions : null} settle={d.settle}
                           rotation={rotation} onSpawn={onSpawn} />
        <Toolbar mode={mode} tool={tool} setTool={setTool} hint={hint} />

        <div style={{ position: 'absolute', top: 10, left: 10, background: 'rgba(0,0,0,0.65)', color: '#e2e8f0', fontSize: 11,
                      borderRadius: 6, padding: '6px 10px', lineHeight: 1.8, pointerEvents: 'none' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', display: 'inline-block', background: connected ? '#4ade80' : '#f87171' }} />
            {connected ? 'Connected' : 'Offline'} · {layout.name}
          </div>
          {build ? <div style={{ color: '#c4b5fd' }}>BUILD MODE{d.dirty ? ' · unsaved changes' : ''}</div> : (
            <>
              <div>Sim time: {simTime.toFixed(1)}s</div>
              <div>Speed: {simState?.time_scale ?? 1}×</div>
              <div style={{ color: simState?.failsafe_reason ? '#fca5a5' : '#86efac' }}>
                Signals: {simState?.failsafe_reason ? `FAILSAFE (${simState.failsafe_reason})` : (simState?.signal_mode === 'fixed' ? 'PROGRAM' : 'AUTO')}
              </div>
            </>
          )}
        </div>

        {error && !build && (
          <div style={{ position: 'absolute', bottom: 10, left: 10, right: 10, background: 'rgba(127,29,29,0.9)', color: '#fca5a5',
                        fontSize: 11, borderRadius: 6, padding: '6px 10px' }}>{error}</div>
        )}
      </main>

      {!build && (
        <aside style={{ width: 300, flexShrink: 0, overflowY: 'auto', background: '#111827', borderLeft: '1px solid #1e293b',
                        padding: 12, color: '#e2e8f0', fontSize: 11 }}>
          <div style={{ marginBottom: 12 }}><CameraView compact /></div>
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 10, color: '#f1f5f9' }}>Live Metrics</div>
          <div style={{ marginBottom: 10 }}>
            <div style={{ color: '#64748b', marginBottom: 4 }}>Traffic Lights</div>
            {lights.map(l => (
              <div key={l.id} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2, gap: 6 }}>
                <span style={{ textTransform: 'capitalize', color: '#cbd5e1' }}>{l.direction}</span>
                <span style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  {Object.entries(l.sections ?? {}).map(([m, s]) => (
                    <span key={m} title={`${m} arrow`} style={{ fontFamily: 'monospace', fontSize: 10, color: LIGHT_COLORS[s] ?? '#888' }}>
                      {SECTION_GLYPH[m] ?? m}
                    </span>
                  ))}
                  <span style={{ fontFamily: 'monospace', fontWeight: 600, color: LIGHT_COLORS[l.state] ?? '#888' }}>{l.state}</span>
                </span>
              </div>
            ))}
          </div>
          <div style={{ marginBottom: 10 }}>
            <div style={{ color: '#64748b', marginBottom: 4 }}>Pedestrian Lights</div>
            {pedestrianLights.map(p => (
              <div key={p.id} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
                <span style={{ textTransform: 'capitalize', color: '#cbd5e1' }}>{p.direction}</span>
                <span style={{ fontFamily: 'monospace', fontWeight: 600, color: LIGHT_COLORS[p.state] ?? '#888' }}>
                  {p.state === 'GREEN' ? 'WALK' : 'DON’T WALK'}
                </span>
              </div>
            ))}
          </div>
          <div style={{ marginBottom: 10 }}>
            <div style={{ color: '#64748b', marginBottom: 4 }}>Приоритет камеры</div>
            <div style={{ color: cameraPriority?.camera_ok ? '#e2e8f0' : '#fbbf24', fontWeight: 600 }}>
              {!cameraPriority?.camera_ok ? 'Таймерный режим · камера недоступна'
                : cameraPriority.recipient === 'pedestrians' ? '🚶 Пешеходам'
                  : cameraPriority.recipient === 'drivers' ? '🚗 Водителям' : 'Очередей нет'}
            </div>
            {cameraPriority?.camera_ok && (
              <div style={{ color: '#94a3b8', marginTop: 2 }}>
                Пешеходов: {cameraPriority.pedestrians} · машин: {cameraPriority.vehicles}
              </div>
            )}
          </div>
          {metrics ? (
            <div>
              <div style={{ color: '#64748b', marginBottom: 4 }}>Performance</div>
              <MRow label="Vehicles" value={metrics.vehicles_active} />
              <MRow label="Waiting" value={metrics.vehicles_waiting} />
              <MRow label="Passed" value={metrics.passed_total} />
              <MRow label="Avg wait" value={`${(metrics.avg_wait_s ?? 0).toFixed(1)}s`} />
              <MRow label="Efficiency" value={`${(metrics.efficiency_pct ?? 0).toFixed(0)}%`} />
              <MRow label="Congestion" value={`${(metrics.congestion_pct ?? 0).toFixed(0)}%`} />
              <MRow label="Light switches" value={metrics.phase_switches} />
              <MRow label="Ped signal switches" value={metrics.ped_signal_switches} />
              <div style={{ color: '#64748b', marginBottom: 4, marginTop: 8 }}>Pedestrians</div>
              <MRow label="Waiting" value={metrics.pedestrians_waiting} />
              <MRow label="Crossing" value={metrics.pedestrians_crossing} />
              <MRow label="Crossed" value={metrics.peds_crossed_total} />
            </div>
          ) : <div style={{ color: '#475569', textAlign: 'center', marginTop: 24 }}>Start a scenario to see metrics</div>}
        </aside>
      )}
    </div>
  )
}

function MRow({ label, value }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
      <span style={{ color: '#94a3b8' }}>{label}</span>
      <span style={{ fontFamily: 'monospace' }}>{value ?? '—'}</span>
    </div>
  )
}
