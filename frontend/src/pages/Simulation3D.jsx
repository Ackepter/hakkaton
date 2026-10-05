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
import { Button } from '@/components/ui/button'
import { Hammer } from 'lucide-react'

const WS_URL = `ws://${window.location.hostname}:8001/ws/state`
const API_URL = `${SI_URL}/simulation/state`
const LIGHT_COLORS = { RED: '#ef4444', YELLOW: '#fbbf24', GREEN: '#22c55e' }
const SECTION_GLYPH = { left: '↰', right: '↱', uturn: '↩' }

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
    <div className="flex h-screen overflow-hidden bg-background">
      <aside className="shrink-0 overflow-y-auto border-r border-border bg-card p-3" style={{ width: build ? 330 : 220 }}>
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
            <Button onClick={edit} data-testid="edit-city" className="mb-3 w-full" size="sm">
              <Hammer className="h-3.5 w-3.5" /> Build mode
            </Button>
            <SimControls simStatus={status} metrics={metrics} cameraFailure={!!simState?.camera_failure}
                         failsafeReason={simState?.failsafe_reason ?? null} />
            {message && <div className="mt-2 text-xs text-success">{message}</div>}
          </>
        )}
      </aside>

      <main className="relative min-w-0 h-full flex-1">
        <IntersectionScene layout={layout} vehicles={vehicles} pedestrians={pedestrians} lights={lights}
                           pedestrianLights={pedestrianLights}
                           cameraStatus={cameraStatus} mode={mode} tool={tool} selection={selection}
                           setSelection={setSelection} actions={draft ? d.actions : null} settle={d.settle}
                           rotation={rotation} onSpawn={onSpawn} />
        <Toolbar mode={mode} tool={tool} setTool={setTool} hint={hint} />

        <div className="pointer-events-none absolute left-2.5 top-2.5 rounded-md bg-black/65 px-2.5 py-1.5 text-xs leading-loose text-foreground">
          <div className="flex items-center gap-1.5">
            <span className={`inline-block h-2 w-2 rounded-full ${connected ? 'bg-green-400' : 'bg-red-400'}`} />
            {connected ? 'Connected' : 'Offline'} · {layout.name}
          </div>
          {build ? <div className="text-violet-300">BUILD MODE{d.dirty ? ' · unsaved changes' : ''}</div> : (
            <>
              <div>Sim time: {simTime.toFixed(1)}s</div>
              <div>Speed: {simState?.time_scale ?? 1}×</div>
              <div className={simState?.failsafe_reason ? 'text-red-300' : 'text-green-300'}>
                Signals: {simState?.failsafe_reason ? `FAILSAFE (${simState.failsafe_reason})` : (simState?.signal_mode === 'fixed' ? 'PROGRAM' : 'AUTO')}
              </div>
            </>
          )}
        </div>

        {error && !build && (
          <div className="absolute bottom-2.5 left-2.5 right-2.5 rounded-md bg-red-950/90 px-2.5 py-1.5 text-xs text-red-300">{error}</div>
        )}
      </main>

      {!build && (
        <aside className="w-[300px] shrink-0 overflow-y-auto border-l border-border bg-card p-3 text-xs">
          <div className="mb-3"><CameraView compact /></div>
          <div className="mb-2.5 text-sm font-semibold">Live Metrics</div>
          <div className="mb-2.5">
            <div className="mb-1 text-muted-foreground">Traffic Lights</div>
            {lights.map(l => (
              <div key={l.id} className="mb-0.5 flex items-center justify-between gap-1.5">
                <span className="capitalize text-foreground/80">{l.direction}</span>
                <span className="flex items-center gap-1.5">
                  {Object.entries(l.sections ?? {}).map(([m, s]) => (
                    <span key={m} title={`${m} arrow`} className="font-mono text-[10px]" style={{ color: LIGHT_COLORS[s] ?? '#888' }}>
                      {SECTION_GLYPH[m] ?? m}
                    </span>
                  ))}
                  <span className="font-mono font-semibold" style={{ color: LIGHT_COLORS[l.state] ?? '#888' }}>{l.state}</span>
                </span>
              </div>
            ))}
          </div>
          <div className="mb-2.5">
            <div className="mb-1 text-muted-foreground">Pedestrian Lights</div>
            {pedestrianLights.map(p => (
              <div key={p.id} className="mb-0.5 flex justify-between">
                <span className="capitalize text-foreground/80">{p.direction}</span>
                <span className="font-mono font-semibold" style={{ color: LIGHT_COLORS[p.state] ?? '#888' }}>
                  {p.state === 'GREEN' ? 'WALK' : 'DON’T WALK'}
                </span>
              </div>
            ))}
          </div>
          <div className="mb-2.5">
            <div className="mb-1 text-muted-foreground">Приоритет камеры</div>
            <div className={`font-semibold ${cameraPriority?.camera_ok ? 'text-foreground' : 'text-amber-400'}`}>
              {!cameraPriority?.camera_ok ? 'Таймерный режим · камера недоступна'
                : cameraPriority.recipient === 'pedestrians' ? '🚶 Пешеходам'
                  : cameraPriority.recipient === 'drivers' ? '🚗 Водителям'
                    : cameraPriority.recipient === 'balanced' ? 'Поровну · обычный режим' : 'Очередей нет'}
            </div>
            {cameraPriority?.camera_ok && (
              <div className="mt-0.5 text-muted-foreground">
                Пешеходов: {cameraPriority.pedestrians} · машин: {cameraPriority.vehicles}
              </div>
            )}
          </div>
          {metrics ? (
            <div>
              <div className="mb-1 text-muted-foreground">Performance</div>
              <MRow label="Vehicles" value={metrics.vehicles_active} />
              <MRow label="Waiting" value={metrics.vehicles_waiting} />
              <MRow label="Passed" value={metrics.passed_total} />
              <MRow label="Avg wait" value={`${(metrics.avg_wait_s ?? 0).toFixed(1)}s`} />
              <MRow label="Efficiency" value={`${(metrics.efficiency_pct ?? 0).toFixed(0)}%`} />
              <MRow label="Congestion" value={`${(metrics.congestion_pct ?? 0).toFixed(0)}%`} />
              <MRow label="Light switches" value={metrics.phase_switches} />
              <MRow label="Ped signal switches" value={metrics.ped_signal_switches} />
              <div className="mb-1 mt-2 text-muted-foreground">Pedestrians</div>
              <MRow label="Waiting" value={metrics.pedestrians_waiting} />
              <MRow label="Crossing" value={metrics.pedestrians_crossing} />
              <MRow label="Crossed" value={metrics.peds_crossed_total} />
            </div>
          ) : <div className="mt-6 text-center text-muted-foreground/60">Start a scenario to see metrics</div>}
        </aside>
      )}
    </div>
  )
}

function MRow({ label, value }) {
  return (
    <div className="mb-0.5 flex justify-between">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono">{value ?? '—'}</span>
    </div>
  )
}
