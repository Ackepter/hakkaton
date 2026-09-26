/**
 * Simulation3D — 3D intersection viewer.
 * Connects to SI microservice on port 8001 via WebSocket; falls back to HTTP polling.
 */
import { useState, useEffect, useRef } from 'react'
import axios from 'axios'
import IntersectionScene from '../components/scene/IntersectionScene'
import SimControls from '../components/scene/SimControls'

const WS_URL  = 'ws://localhost:8001/ws/state'
const API_URL = 'http://localhost:8001/simulation/state'

const LIGHT_COLORS = { RED: '#ef4444', YELLOW: '#fbbf24', GREEN: '#22c55e' }

const NAV_H = 56  // px — must match App.jsx nav height

export default function Simulation3D() {
  const [simState, setSimState]   = useState(null)
  const [connected, setConnected] = useState(false)
  const [error, setError]         = useState(null)
  const wsRef   = useRef(null)
  const pollRef = useRef(null)

  useEffect(() => {
    let alive = true

    function startPolling() {
      if (pollRef.current) return
      pollRef.current = setInterval(async () => {
        try {
          const r = await axios.get(API_URL)
          if (alive) { setSimState(r.data); setConnected(true); setError(null) }
        } catch {
          if (alive) {
            setConnected(false)
            setError('SI service offline — запустите start.bat')
          }
        }
      }, 500)
    }

    function connectWS() {
      if (!alive) return
      try {
        const ws = new WebSocket(WS_URL)
        wsRef.current = ws
        ws.onopen  = () => { if (alive) { setConnected(true); setError(null) }
                              if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null } }
        ws.onmessage = e => { try { if (alive) setSimState(JSON.parse(e.data)) } catch {} }
        ws.onclose   = () => { if (alive) { setConnected(false); startPolling(); setTimeout(connectWS, 3000) } }
        ws.onerror   = () => ws.close()
      } catch {
        startPolling()
      }
    }

    connectWS()
    return () => {
      alive = false
      wsRef.current?.close()
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  const vehicles    = simState?.vehicles    ?? []
  const pedestrians = simState?.pedestrians ?? []
  const lights      = simState?.lights      ?? []
  const metrics     = simState?.metrics     ?? null
  const status      = simState?.status      ?? 'stopped'
  const simTime     = simState?.sim_time    ?? 0

  return (
    <div style={{
      display: 'flex',
      height: `calc(100vh - ${NAV_H}px)`,
      overflow: 'hidden',
      background: '#0f172a',
    }}>

      {/* Left panel — controls */}
      <aside style={{
        width: 200, flexShrink: 0, overflowY: 'auto',
        background: '#111827', borderRight: '1px solid #1e293b',
        padding: 12,
      }}>
        <SimControls simStatus={status} metrics={metrics} />
      </aside>

      {/* Centre — 3D canvas (fills all remaining space) */}
      <main style={{ flex: 1, position: 'relative', minWidth: 0, height: '100%' }}>
        <IntersectionScene vehicles={vehicles} pedestrians={pedestrians} lights={lights} />

        {/* HUD overlay */}
        <div style={{
          position: 'absolute', top: 10, left: 10,
          background: 'rgba(0,0,0,0.65)', color: '#e2e8f0',
          fontSize: 11, borderRadius: 6, padding: '6px 10px', lineHeight: 1.8,
          pointerEvents: 'none',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ width: 8, height: 8, borderRadius: '50%', display: 'inline-block',
                           background: connected ? '#4ade80' : '#f87171' }} />
            {connected ? 'Connected' : 'Offline'}
          </div>
          <div>Sim time: {simTime.toFixed(1)}s</div>
          <div>Speed: {simState?.time_scale ?? 1}×</div>
        </div>

        {error && (
          <div style={{
            position: 'absolute', bottom: 10, left: 10, right: 10,
            background: 'rgba(127,29,29,0.9)', color: '#fca5a5',
            fontSize: 11, borderRadius: 6, padding: '6px 10px',
          }}>
            {error}
          </div>
        )}
      </main>

      {/* Right panel — metrics */}
      <aside style={{
        width: 170, flexShrink: 0, overflowY: 'auto',
        background: '#111827', borderLeft: '1px solid #1e293b',
        padding: 12, color: '#e2e8f0', fontSize: 11,
      }}>
        <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 10, color: '#f1f5f9' }}>
          Live Metrics
        </div>

        <div style={{ marginBottom: 10 }}>
          <div style={{ color: '#64748b', marginBottom: 4 }}>Traffic Lights</div>
          {lights.map(l => (
            <div key={l.id} style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
              <span style={{ textTransform: 'capitalize', color: '#cbd5e1' }}>{l.direction}</span>
              <span style={{ fontFamily: 'monospace', fontWeight: 600, color: LIGHT_COLORS[l.state] ?? '#888' }}>
                {l.state}
              </span>
            </div>
          ))}
        </div>

        {metrics ? (
          <div>
            <div style={{ color: '#64748b', marginBottom: 4 }}>Performance</div>
            <MRow label="Vehicles"   value={metrics.vehicles_active} />
            <MRow label="Waiting"    value={metrics.vehicles_waiting} />
            <MRow label="Passed"     value={metrics.passed_total} />
            <MRow label="Avg wait"   value={`${(metrics.avg_wait_s ?? 0).toFixed(1)}s`} />
            <MRow label="Efficiency" value={`${(metrics.efficiency_pct ?? 0).toFixed(0)}%`} />
            <MRow label="Congestion" value={`${(metrics.congestion_pct ?? 0).toFixed(0)}%`} />
            <div style={{ color: '#64748b', marginBottom: 4, marginTop: 8 }}>Pedestrians</div>
            <MRow label="Waiting"  value={metrics.pedestrians_waiting} />
            <MRow label="Crossing" value={metrics.pedestrians_crossing} />
            <MRow label="Crossed"  value={metrics.peds_crossed_total} />
          </div>
        ) : (
          <div style={{ color: '#475569', textAlign: 'center', marginTop: 24 }}>
            Start a scenario to see metrics
          </div>
        )}
      </aside>
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
