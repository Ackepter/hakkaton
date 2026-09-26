/**
 * Simulation3D page — 3D intersection viewer with controls.
 * Connects to SI microservice on port 8001 via WebSocket.
 * Falls back to HTTP polling every 500ms.
 */
import { useState, useEffect, useRef } from 'react'
import axios from 'axios'
import IntersectionScene from '../components/scene/IntersectionScene'
import SimControls from '../components/scene/SimControls'

const WS_URL = 'ws://localhost:8001/ws/state'
const API_URL = 'http://localhost:8001/simulation/state'

const LIGHT_COLORS = { RED: '#ef4444', YELLOW: '#fbbf24', GREEN: '#22c55e' }

export default function Simulation3D() {
  const [simState, setSimState] = useState(null)
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState(null)
  const wsRef = useRef(null)
  const pollRef = useRef(null)

  // Try WebSocket first, fall back to HTTP polling
  useEffect(() => {
    let useWs = true

    function connectWS() {
      if (!useWs) return
      try {
        const ws = new WebSocket(WS_URL)
        wsRef.current = ws

        ws.onopen = () => {
          setConnected(true)
          setError(null)
          if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
        }
        ws.onmessage = (e) => {
          try { setSimState(JSON.parse(e.data)) } catch {}
        }
        ws.onclose = () => {
          setConnected(false)
          if (useWs) {
            startPolling()
            setTimeout(connectWS, 3000)
          }
        }
        ws.onerror = () => {
          ws.close()
        }
      } catch {
        startPolling()
      }
    }

    function startPolling() {
      if (pollRef.current) return
      pollRef.current = setInterval(async () => {
        try {
          const r = await axios.get(API_URL)
          setSimState(r.data)
          setConnected(true)
          setError(null)
        } catch (e) {
          setConnected(false)
          setError('SI service offline — start it with: python -m uvicorn smart_intersection.main:app --port 8001')
        }
      }, 500)
    }

    connectWS()

    return () => {
      useWs = false
      if (wsRef.current) wsRef.current.close()
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
    <div className="flex h-screen overflow-hidden bg-gray-950" style={{ height: 'calc(100vh - 56px)' }}>

      {/* Left panel — controls */}
      <aside className="w-56 flex-none p-3 overflow-y-auto bg-gray-900 border-r border-gray-800">
        <SimControls simStatus={status} metrics={metrics} />
      </aside>

      {/* Center — 3D canvas */}
      <main className="flex-1 relative">
        <IntersectionScene vehicles={vehicles} pedestrians={pedestrians} lights={lights} />

        {/* Overlay: sim time + connection */}
        <div className="absolute top-3 left-3 text-white text-xs bg-black/60 rounded px-2 py-1 space-y-0.5">
          <div className="flex items-center gap-1.5">
            <span className={`w-2 h-2 rounded-full ${connected ? 'bg-green-400' : 'bg-red-500'}`} />
            <span>{connected ? 'Connected' : 'Offline'}</span>
          </div>
          <div>Sim time: {simTime.toFixed(1)}s</div>
          <div>Speed: {simState?.time_scale ?? 1}×</div>
        </div>

        {/* Error banner */}
        {error && (
          <div className="absolute bottom-3 left-3 right-3 bg-red-900/80 text-red-200 text-xs rounded p-2">
            {error}
          </div>
        )}
      </main>

      {/* Right panel — metrics */}
      <aside className="w-48 flex-none p-3 overflow-y-auto bg-gray-900 border-l border-gray-800 text-white text-xs space-y-4">
        <h3 className="font-semibold text-gray-200 text-sm">Live Metrics</h3>

        {/* Traffic lights */}
        <div>
          <p className="text-gray-400 mb-1">Traffic Lights</p>
          {lights.map(l => (
            <div key={l.id} className="flex items-center justify-between mb-0.5">
              <span className="text-gray-300 capitalize">{l.direction}</span>
              <span className="font-mono" style={{ color: LIGHT_COLORS[l.state] ?? '#888' }}>
                {l.state}
              </span>
            </div>
          ))}
        </div>

        {metrics && (
          <div className="space-y-1">
            <p className="text-gray-400">Performance</p>
            <Metric label="Vehicles" value={metrics.vehicles_active} />
            <Metric label="Waiting" value={metrics.vehicles_waiting} />
            <Metric label="Passed" value={metrics.passed_total} />
            <Metric label="Avg wait" value={`${metrics.avg_wait_s?.toFixed(1)}s`} />
            <Metric label="Efficiency" value={`${metrics.efficiency_pct?.toFixed(0)}%`} />
            <Metric label="Congestion" value={`${metrics.congestion_pct?.toFixed(0)}%`} />
            <p className="text-gray-400 mt-2">Pedestrians</p>
            <Metric label="Waiting" value={metrics.pedestrians_waiting} />
            <Metric label="Crossing" value={metrics.pedestrians_crossing} />
            <Metric label="Crossed" value={metrics.peds_crossed_total} />
          </div>
        )}

        {!simState && (
          <p className="text-gray-500 text-center mt-8">
            Start the SI service on port 8001
          </p>
        )}
      </aside>
    </div>
  )
}

function Metric({ label, value }) {
  return (
    <div className="flex justify-between">
      <span className="text-gray-400">{label}</span>
      <span className="font-mono">{value ?? '—'}</span>
    </div>
  )
}
