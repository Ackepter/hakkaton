/**
 * SimControls — play/pause/speed/scenario panel.
 * Speed slider: local state updates on onChange, API call fires only on mouseUp/touchEnd.
 */
import { useState } from 'react'
import axios from 'axios'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/input'

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
    <div className="text-sm">
      <div className="mb-3 text-sm font-semibold">Simulation Controls</div>

      {/* Scenario picker */}
      <div className="mb-2.5">
        <div className="mb-1 text-[11px] text-muted-foreground">Scenario</div>
        <Select value={scenario} onChange={e => setScenario(e.target.value)} className="w-full">
          {SCENARIOS.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
        </Select>
      </div>

      {/* Action buttons */}
      <div className="mb-2.5 flex flex-wrap gap-1.5">
        <Button size="sm" onClick={handleStart} disabled={isRunning} className="bg-success hover:bg-success/90">▶ Start</Button>
        <Button size="sm" onClick={handlePause} disabled={!isRunning && !isPaused} variant={isPaused ? 'default' : 'secondary'}>
          {isPaused ? '▶ Resume' : '⏸ Pause'}
        </Button>
        <Button size="sm" onClick={handleReset} variant="secondary">↺ Reset</Button>
      </div>

      {/* Signal control mode */}
      <div className="mb-2.5">
        <div className="mb-1 text-[11px] text-muted-foreground">Signal control</div>
        <Select value={controlMode} className="w-full"
          onChange={e => { setControlMode(e.target.value); call('post', '/simulation/config', { control_mode: e.target.value }) }}>
          <option value="auto">Camera analysis (AUTO)</option>
          <option value="failsafe">Timer (fixed timing)</option>
        </Select>
      </div>

      {/* Camera failure (scenario "Camera/Detection Failure") */}
      <Button size="sm" className="mb-2.5 w-full" variant={cameraFailure ? 'destructive' : 'secondary'}
        onClick={() => call('post', '/simulation/camera-failure', { active: !cameraFailure })}>
        {cameraFailure ? '📷 Вернуть камеру' : '📷 Сбой камеры'}
      </Button>
      {failsafeReason && (
        <div className="mb-2.5 text-[11px] text-destructive">FAILSAFE: {failsafeReason}</div>
      )}

      {/* Speed slider */}
      <div className="mb-3">
        <div className="mb-1 text-[11px] text-muted-foreground">
          Speed: <strong className="text-foreground">{timeScale}×</strong>
        </div>
        <input
          type="range" min="0.25" max="10" step="0.25"
          value={timeScale}
          onChange={e => setTimeScale(parseFloat(e.target.value))}
          onMouseUp={handleSpeedRelease}
          onTouchEnd={handleSpeedRelease}
          className="w-full cursor-pointer accent-primary"
        />
        <div className="flex justify-between text-[10px] text-muted-foreground">
          <span>0.25×</span><span>10×</span>
        </div>
      </div>

      {/* Status */}
      <div className="border-t border-border pt-2 text-[11px] text-muted-foreground">
        <div className="mb-1 flex justify-between">
          <span>Status</span>
          <span className={`font-semibold ${isRunning ? 'text-green-400' : isPaused ? 'text-amber-400' : 'text-muted-foreground'}`}>
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
    <div className="mb-0.5 flex justify-between">
      <span>{label}</span>
      <span className="font-mono text-foreground/80">{value}</span>
    </div>
  )
}
