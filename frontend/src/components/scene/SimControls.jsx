/**
 * SimControls — play/pause/speed/scenario panel.
 */
import { useState } from 'react'
import axios from 'axios'

const SI_URL = 'http://localhost:8001'

const SCENARIOS = [
  { id: 'empty', name: 'Empty' },
  { id: 'normal', name: 'Normal Traffic' },
  { id: 'heavy', name: 'Heavy Traffic' },
  { id: 'pedestrian_rush', name: 'Pedestrian Rush' },
  { id: 'unbalanced', name: 'Unbalanced (North)' },
  { id: 'emergency', name: 'Emergency Vehicles' },
  { id: 'traffic_jam', name: 'Traffic Jam' },
  { id: 'failsafe', name: 'Failsafe Mode' },
  { id: 'demo_city_intersection', name: 'Full Demo' },
]

export default function SimControls({ simStatus, metrics }) {
  const [scenario, setScenario] = useState('normal')
  const [timeScale, setTimeScale] = useState(1)
  const [loading, setLoading] = useState(false)

  const call = async (method, path, body) => {
    setLoading(true)
    try {
      await axios({ method, url: `${SI_URL}${path}`, data: body })
    } catch (e) {
      console.error('SI API error:', e)
    } finally {
      setLoading(false)
    }
  }

  const handleStart = () => call('post', '/scenario/start', { scenario_id: scenario })
  const handleStop  = () => call('post', '/simulation/stop')
  const handlePause = () =>
    simStatus === 'paused'
      ? call('post', '/simulation/resume')
      : call('post', '/simulation/pause')
  const handleReset = () => call('post', '/simulation/reset')
  const handleSpeedChange = async (val) => {
    setTimeScale(val)
    await call('post', '/simulation/config', { time_scale: parseFloat(val) })
  }

  const btnBase = 'px-3 py-1.5 rounded text-sm font-medium disabled:opacity-50 transition-colors'
  const isRunning = simStatus === 'running'
  const isPaused = simStatus === 'paused'

  return (
    <div className="bg-gray-900 text-white p-4 rounded-lg space-y-4 min-w-[220px]">
      <h3 className="text-base font-semibold text-gray-200">Simulation Controls</h3>

      {/* Scenario picker */}
      <div>
        <label className="text-xs text-gray-400 block mb-1">Scenario</label>
        <select
          value={scenario}
          onChange={e => setScenario(e.target.value)}
          className="w-full bg-gray-800 text-white text-sm rounded px-2 py-1.5 border border-gray-700"
        >
          {SCENARIOS.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
      </div>

      {/* Action buttons */}
      <div className="flex flex-wrap gap-2">
        <button
          onClick={handleStart}
          disabled={loading || isRunning}
          className={`${btnBase} bg-green-600 hover:bg-green-700`}
        >▶ Start</button>

        <button
          onClick={handlePause}
          disabled={loading || (!isRunning && !isPaused)}
          className={`${btnBase} ${isPaused ? 'bg-blue-600 hover:bg-blue-700' : 'bg-yellow-600 hover:bg-yellow-700'}`}
        >{isPaused ? '▶ Resume' : '⏸ Pause'}</button>

        <button
          onClick={handleStop}
          disabled={loading || (!isRunning && !isPaused)}
          className={`${btnBase} bg-red-600 hover:bg-red-700`}
        >⏹ Stop</button>

        <button
          onClick={handleReset}
          disabled={loading}
          className={`${btnBase} bg-gray-600 hover:bg-gray-700`}
        >↺ Reset</button>
      </div>

      {/* Speed */}
      <div>
        <label className="text-xs text-gray-400 block mb-1">Speed: {timeScale}×</label>
        <input
          type="range" min="0.25" max="10" step="0.25"
          value={timeScale}
          onChange={e => handleSpeedChange(e.target.value)}
          className="w-full"
        />
      </div>

      {/* Status */}
      <div className="text-xs text-gray-400 space-y-1">
        <div className="flex justify-between">
          <span>Status</span>
          <span className={`font-medium ${isRunning ? 'text-green-400' : isPaused ? 'text-yellow-400' : 'text-gray-500'}`}>
            {simStatus || 'stopped'}
          </span>
        </div>
        {metrics && (
          <>
            <div className="flex justify-between">
              <span>Active vehicles</span>
              <span>{metrics.vehicles_active ?? 0}</span>
            </div>
            <div className="flex justify-between">
              <span>Waiting</span>
              <span>{metrics.vehicles_waiting ?? 0}</span>
            </div>
            <div className="flex justify-between">
              <span>Passed total</span>
              <span>{metrics.passed_total ?? 0}</span>
            </div>
            <div className="flex justify-between">
              <span>Avg wait</span>
              <span>{metrics.avg_wait_s?.toFixed(1) ?? 0}s</span>
            </div>
            <div className="flex justify-between">
              <span>Efficiency</span>
              <span>{metrics.efficiency_pct?.toFixed(0) ?? 0}%</span>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
