/**
 * SimControls — play/pause/speed/scenario panel.
 * Speed slider: local state updates on onChange, API call fires only on mouseUp/touchEnd.
 */
import { useState } from 'react'
import axios from 'axios'

const SI_URL = 'http://localhost:8001'

const SCENARIOS = [
  { id: 'empty',                  name: 'Empty' },
  { id: 'normal',                 name: 'Normal Traffic' },
  { id: 'heavy',                  name: 'Heavy Traffic' },
  { id: 'pedestrian_rush',        name: 'Pedestrian Rush' },
  { id: 'unbalanced',             name: 'Unbalanced (North)' },
  { id: 'emergency',              name: 'Emergency Vehicles' },
  { id: 'traffic_jam',            name: 'Traffic Jam' },
  { id: 'failsafe',               name: 'Failsafe Mode' },
  { id: 'demo_city_intersection', name: 'Full Demo' },
]

export default function SimControls({ simStatus, metrics, cameraFailure = false, failsafeReason = null }) {
  const [scenario, setScenario] = useState('normal')
  const [timeScale, setTimeScale] = useState(1)
  const [controlMode, setControlMode] = useState('auto')

  const call = async (method, path, body) => {
    try {
      await axios({ method, url: `${SI_URL}${path}`, data: body })
    } catch (e) {
      console.error('SI API error:', e?.response?.status, path)
    }
  }

  const handleStart = () => {
    setControlMode(scenario === 'failsafe' ? 'failsafe' : 'auto')
    return call('post', '/scenario/start', { scenario_id: scenario })
  }
  const handlePause = () =>
    simStatus === 'paused'
      ? call('post', '/simulation/resume')
      : call('post', '/simulation/pause')
  const handleReset = () => call('post', '/simulation/reset')

  // Slider: update local display immediately, send API only on release
  const handleSpeedRelease = (e) => {
    const val = parseFloat(e.target.value)
    setTimeScale(val)
    call('post', '/simulation/config', { time_scale: val })
  }

  const isRunning = simStatus === 'running'
  const isPaused  = simStatus === 'paused'

  return (
    <div style={{ color: '#fff', fontSize: 13 }}>
      <div style={{ fontWeight: 600, marginBottom: 12, fontSize: 14, color: '#e2e8f0' }}>
        Simulation Controls
      </div>

      {/* Scenario picker */}
      <div style={{ marginBottom: 10 }}>
        <div style={{ color: '#94a3b8', fontSize: 11, marginBottom: 4 }}>Scenario</div>
        <select
          value={scenario}
          onChange={e => setScenario(e.target.value)}
          style={{
            width: '100%', background: '#1e293b', color: '#fff',
            border: '1px solid #334155', borderRadius: 4, padding: '4px 6px', fontSize: 12,
          }}
        >
          {SCENARIOS.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </div>

      {/* Action buttons */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 10 }}>
        <button
          onClick={handleStart}
          disabled={isRunning}
          style={btnStyle(isRunning ? '#166534' : '#15803d')}
        >▶ Start</button>

        <button
          onClick={handlePause}
          disabled={!isRunning && !isPaused}
          style={btnStyle(isPaused ? '#1d4ed8' : '#b45309')}
        >{isPaused ? '▶ Resume' : '⏸ Pause'}</button>

        <button
          onClick={handleReset}
          style={btnStyle('#374151')}
        >↺ Reset</button>
      </div>

      {/* Signal control mode */}
      <div style={{ marginBottom: 10 }}>
        <div style={{ color: '#94a3b8', fontSize: 11, marginBottom: 4 }}>Signal control</div>
        <select
          value={controlMode}
          onChange={e => { setControlMode(e.target.value); call('post', '/simulation/config', { control_mode: e.target.value }) }}
          style={{ width: '100%', background: '#1e293b', color: '#fff', border: '1px solid #334155', borderRadius: 4, padding: '4px 6px', fontSize: 12 }}
        >
          <option value="auto">Camera analysis (AUTO)</option>
          <option value="failsafe">Timer (fixed timing)</option>
        </select>
      </div>

      {/* Camera failure (scenario "Camera/Detection Failure") */}
      <button
        onClick={() => call('post', '/simulation/camera-failure', { active: !cameraFailure })}
        style={{ ...btnStyle(cameraFailure ? '#b91c1c' : '#374151'), width: '100%', marginBottom: 10 }}
      >{cameraFailure ? '📷 Вернуть камеру' : '📷 Сбой камеры'}</button>
      {failsafeReason && (
        <div style={{ color: '#fca5a5', fontSize: 11, marginBottom: 10 }}>FAILSAFE: {failsafeReason}</div>
      )}

      {/* Speed slider */}
      <div style={{ marginBottom: 12 }}>
        <div style={{ color: '#94a3b8', fontSize: 11, marginBottom: 4 }}>
          Speed: <strong style={{ color: '#fff' }}>{timeScale}×</strong>
        </div>
        <input
          type="range" min="0.25" max="10" step="0.25"
          value={timeScale}
          onChange={e => setTimeScale(parseFloat(e.target.value))}
          onMouseUp={handleSpeedRelease}
          onTouchEnd={handleSpeedRelease}
          style={{ width: '100%', cursor: 'pointer' }}
        />
        <div style={{ display: 'flex', justifyContent: 'space-between', color: '#64748b', fontSize: 10 }}>
          <span>0.25×</span><span>10×</span>
        </div>
      </div>

      {/* Status */}
      <div style={{ borderTop: '1px solid #1e293b', paddingTop: 8, fontSize: 11, color: '#94a3b8' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
          <span>Status</span>
          <span style={{ color: isRunning ? '#4ade80' : isPaused ? '#fbbf24' : '#64748b', fontWeight: 600 }}>
            {simStatus || 'stopped'}
          </span>
        </div>
        {metrics && (
          <>
            <StatRow label="Active" value={metrics.vehicles_active ?? 0} />
            <StatRow label="Waiting" value={metrics.vehicles_waiting ?? 0} />
            <StatRow label="Passed" value={metrics.passed_total ?? 0} />
            <StatRow label="Avg wait" value={`${(metrics.avg_wait_s ?? 0).toFixed(1)}s`} />
            <StatRow label="Efficiency" value={`${(metrics.efficiency_pct ?? 0).toFixed(0)}%`} />
          </>
        )}
      </div>
    </div>
  )
}

function StatRow({ label, value }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 2 }}>
      <span>{label}</span>
      <span style={{ fontFamily: 'monospace', color: '#cbd5e1' }}>{value}</span>
    </div>
  )
}

function btnStyle(bg) {
  return {
    background: bg, color: '#fff', border: 'none', borderRadius: 4,
    padding: '5px 10px', fontSize: 12, cursor: 'pointer', fontWeight: 500,
  }
}
