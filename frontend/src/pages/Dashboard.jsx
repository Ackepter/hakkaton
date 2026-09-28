import { useState, useEffect } from 'react'
import { useWebSocket } from '../hooks/useWebSocket'
import api, { controlApi, lightsApi } from '../api/client'
import CameraView from '../components/CameraView'
import { Card, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, AreaChart, Area, BarChart, Bar, Legend
} from 'recharts'

const LIGHT_COLORS = { RED: '#fc8181', YELLOW: '#f6e05e', GREEN: '#68d391', FLASHING_YELLOW: '#f6e05e', OFF: '#4a5568' }
const SECTION_GLYPH = { left: '↰', right: '↱', uturn: '↩' }
const MODE_COLORS = { AUTO: '#68d391', MANUAL: '#63b3ed', FAILSAFE: '#fc8181' }
const CONGESTION_COLORS = { CLEAR: '#68d391', MODERATE: '#f6e05e', CONGESTED: '#ed8936', GRIDLOCK: '#fc8181' }
const CHART_TOOLTIP = { background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', color: 'hsl(var(--foreground))', fontSize: 12 }
const CHART_TICK = { fill: 'hsl(var(--muted-foreground))', fontSize: 10 }

function TrafficLightBulb({ state, size = 28 }) {
  const states = ['RED', 'YELLOW', 'GREEN']
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-border bg-background p-2">
      {states.map(s => (
        <div key={s} style={{
          width: size, height: size, borderRadius: '50%',
          background: state === s ? LIGHT_COLORS[s] : 'hsl(var(--border))',
          boxShadow: state === s ? `0 0 12px ${LIGHT_COLORS[s]}` : 'none',
          transition: 'all 0.3s',
        }} />
      ))}
    </div>
  )
}

function ModeButton({ mode, current, onClick }) {
  const active = current === mode
  return (
    <button
      className="rounded-md border-2 px-4 py-1.5 text-xs font-bold transition-colors"
      style={{
        borderColor: MODE_COLORS[mode],
        background: active ? MODE_COLORS[mode] + '33' : 'transparent',
        color: active ? MODE_COLORS[mode] : 'hsl(var(--muted-foreground))',
      }}
      onClick={() => onClick(mode)}
    >
      {mode}
    </button>
  )
}

function StatCard({ label, value, unit, color }) {
  return (
    <Card className="min-w-[130px] px-4.5 py-3.5">
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="text-2xl font-bold" style={{ color: color || 'hsl(var(--foreground))' }}>{value}</div>
      {unit && <div className="text-[11px] text-muted-foreground">{unit}</div>}
    </Card>
  )
}

export default function Dashboard() {
  const { connected, lastMessage } = useWebSocket()
  const [wsData, setWsData] = useState(null)
  const [chartData, setChartData] = useState([])
  const [mode, setMode] = useState('AUTO')
  const [failsafeReason, setFailsafeReason] = useState(null)
  const [lights, setLights] = useState([])
  const [simRunning, setSimRunning] = useState(false)
  const [siLights, setSiLights] = useState([])
  const [siPedLights, setSiPedLights] = useState([])

  // Smart Intersection lights (XML -> backend parser -> JSON). Shown when the backend controller has none.
  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const r = await api.get('/api/si/state')
        if (alive) {
          setSiLights((r.data.lights || []).map(l => ({ ...l, time_remaining: 0, from_si: true })))
          setSiPedLights(r.data.pedestrian_lights || [])
        }
      } catch {
        if (alive) { setSiLights([]); setSiPedLights([]) }
      }
    }
    load()
    const t = setInterval(load, 1500)
    return () => { alive = false; clearInterval(t) }
  }, [])

  useEffect(() => {
    if (!lastMessage || lastMessage.type !== 'state_update') return
    setWsData(lastMessage)
    setMode(lastMessage.mode)
    setFailsafeReason(lastMessage.failsafe_reason)
    setLights(lastMessage.lights || [])
    setSimRunning(lastMessage.simulation_running)

    const m = lastMessage.metrics?.traffic || {}
    setChartData(prev => {
      const next = [...prev, {
        t: Math.round(lastMessage.ts % 10000),
        cars: m.total_cars || 0,
        trucks: m.total_trucks || 0,
        pedestrians: m.total_pedestrians || 0,
        waitCar: m.avg_car_wait || 0,
        waitPed: m.avg_pedestrian_wait || 0,
        throughput: m.throughput || 0,
      }]
      return next.slice(-60)
    })
  }, [lastMessage])

  const handleModeChange = async (newMode) => {
    try {
      await controlApi.setMode(newMode)
      setMode(newMode)
    } catch {}
  }

  const handleManualLight = async (lightId, state) => {
    try {
      await lightsApi.manualControl(lightId, state)
    } catch (e) {
      console.error(e)
    }
  }

  const handleSimControl = async (action) => {
    try {
      await controlApi.simulationControl(action)
      if (action === 'start') setSimRunning(true)
      else if (action === 'stop') setSimRunning(false)
    } catch {}
  }

  const shownLights = lights.length ? lights : siLights
  const traffic = wsData?.metrics?.traffic || {}
  const system = wsData?.metrics?.system || {}
  const extra = wsData?.metrics?.extra || {}

  return (
    <div className="flex min-h-screen flex-col gap-3 p-4">
      {/* Top status bar */}
      <Card className="flex flex-wrap items-center gap-4 px-5 py-2.5">
        <div className="flex items-center gap-2">
          <div className={cn('h-2 w-2 rounded-full', connected ? 'bg-success' : 'bg-destructive')} />
          <span className={cn('text-sm', connected ? 'text-success' : 'text-destructive')}>
            {connected ? 'Подключено' : 'Отключено'}
          </span>
        </div>
        <div className="flex gap-2">
          <ModeButton mode="AUTO" current={mode} onClick={handleModeChange} />
          <ModeButton mode="MANUAL" current={mode} onClick={handleModeChange} />
          <ModeButton mode="FAILSAFE" current={mode} onClick={handleModeChange} />
        </div>
        {failsafeReason && (
          <Badge variant="destructive">⚠ FAILSAFE: {failsafeReason}</Badge>
        )}
        <div className="ml-auto flex gap-2">
          <Button size="sm" variant={simRunning ? 'destructive' : 'default'} onClick={() => handleSimControl(simRunning ? 'stop' : 'start')}>
            {simRunning ? '⏹ Стоп симуляции' : '▶ Запуск симуляции'}
          </Button>
          <Button size="sm" variant="secondary" onClick={() => handleSimControl('reset')}>↺ Сброс</Button>
        </div>
      </Card>

      <div className="flex flex-wrap gap-3">
        {/* Camera with recognition results (left) */}
        <div className="min-w-[300px] max-w-[560px] flex-[1_1_380px]">
          <CameraView />
        </div>

        {/* Traffic lights panel (right) */}
        <Card className="min-w-[280px] flex-none p-4">
          <CardTitle className="mb-3 flex items-center gap-2 text-sm">
            🚦 Светофоры{shownLights.length > 0 && shownLights[0].from_si ? ' · Smart Intersection' : ''}
          </CardTitle>
          {shownLights.length === 0 && (
            <div className="text-sm text-muted-foreground">Нет данных о светофорах (запустите Smart Intersection)</div>
          )}
          <div className="flex flex-col gap-2.5">
            {shownLights.map(light => (
              <div key={light.id} className="flex items-center gap-3 rounded-lg bg-background px-3 py-2">
                <TrafficLightBulb state={light.state} size={20} />
                <div className="flex-1">
                  <div className="text-sm font-semibold">{light.id}</div>
                  <div className="text-[11px] text-muted-foreground">
                    {light.direction || '—'} · фаза {light.phase_index + 1}
                  </div>
                  <div className="text-[11px] text-muted-foreground">
                    {light.from_si ? `переключений: ${light.phase_switches}` : `Осталось: ${Math.round(light.time_remaining)}с`}
                  </div>
                  {light.sections && Object.keys(light.sections).length > 0 && (
                    <div className="mt-0.5 flex gap-2 text-[11px]">
                      {Object.entries(light.sections).map(([m, st]) => (
                        <span key={m} style={{ color: LIGHT_COLORS[st] }}>{SECTION_GLYPH[m] ?? m} {st}</span>
                      ))}
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-1">
                  <div className="rounded px-2 py-0.5 text-[11px] font-bold" style={{ background: LIGHT_COLORS[light.state] + '22', color: LIGHT_COLORS[light.state] }}>
                    {light.state}
                  </div>
                </div>
                {mode === 'MANUAL' && !light.from_si && (
                  <div className="flex gap-1">
                    {['RED', 'YELLOW', 'GREEN'].map(st => (
                      <button key={st} className="h-3.5 w-3.5 cursor-pointer rounded-full"
                        style={{ background: LIGHT_COLORS[st], border: light.state === st ? '2px solid #fff' : '2px solid transparent' }}
                        onClick={() => handleManualLight(light.id, st)} />
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </Card>

        {/* Pedestrian lights panel */}
        {siPedLights.length > 0 && (
          <Card className="min-w-[220px] flex-none p-4">
            <CardTitle className="mb-3 text-sm">🚶 Пешеходные светофоры</CardTitle>
            <div className="flex flex-col gap-2">
              {siPedLights.map(p => (
                <div key={p.id} className="flex items-center justify-between gap-2 rounded-lg bg-background px-3 py-2">
                  <div>
                    <div className="text-sm font-semibold">{p.id}</div>
                    <div className="text-[11px] text-muted-foreground">
                      переключений: {p.phase_switches} · ждут: {p.waiting_peds} · переходят: {p.crossing_peds}
                    </div>
                  </div>
                  <div className="rounded px-2 py-0.5 text-[11px] font-bold" style={{ background: LIGHT_COLORS[p.state] + '22', color: LIGHT_COLORS[p.state] }}>
                    {p.state === 'GREEN' ? 'ИДИТЕ' : 'СТОЙТЕ'}
                  </div>
                </div>
              ))}
            </div>
          </Card>
        )}

        {/* Stats */}
        <div className="flex flex-1 flex-col gap-3">
          {/* KPI row */}
          <div className="flex flex-wrap gap-2.5">
            <StatCard label="Авто в очереди" value={traffic.total_cars || 0} color="#63b3ed" />
            <StatCard label="Грузовики" value={traffic.total_trucks || 0} color="#ed8936" />
            <StatCard label="Пешеходы" value={traffic.total_pedestrians || 0} color="#b794f4" />
            <StatCard label="Авт/час" value={Math.round(traffic.cars_per_hour || 0)} unit="авт/час" color="#68d391" />
            <StatCard label="Ожидание авто" value={`${(traffic.avg_car_wait || 0).toFixed(1)}`} unit="секунд" color={traffic.avg_car_wait > 30 ? '#fc8181' : '#68d391'} />
            <StatCard label="Ожидание пеш." value={`${(traffic.avg_pedestrian_wait || 0).toFixed(1)}`} unit="секунд" color={traffic.avg_pedestrian_wait > 40 ? '#fc8181' : '#68d391'} />
            <StatCard label="Пропускная сп." value={traffic.throughput || 0} unit="прошло" color="#48bb78" />
            <StatCard label="Эффективность" value={`${extra.efficiency_score || 100}%`} color={extra.efficiency_score > 70 ? '#68d391' : '#fc8181'} />
          </div>

          {/* Additional badges */}
          <div className="flex flex-wrap gap-2">
            {extra.congestion_level && (
              <Badge style={{ background: CONGESTION_COLORS[extra.congestion_level] + '22', color: CONGESTION_COLORS[extra.congestion_level], borderColor: CONGESTION_COLORS[extra.congestion_level] + '44' }}>
                Трафик: {extra.congestion_level}
              </Badge>
            )}
            {extra.pedestrian_risk && (
              <Badge style={{ background: '#b794f422', color: '#b794f4', borderColor: '#b794f444' }}>
                Риск пешеходов: {extra.pedestrian_risk}
              </Badge>
            )}
            <Badge variant="secondary">Переключений: {system.phase_switches || 0}</Badge>
            <Badge variant="secondary">Аптайм: {Math.floor((system.uptime_seconds || 0) / 60)}м {Math.round((system.uptime_seconds || 0) % 60)}с</Badge>
          </div>
        </div>
      </div>

      {/* Charts row */}
      <div className="flex flex-wrap gap-3">
        {/* Vehicle count chart */}
        <Card className="min-w-[300px] flex-1 p-4">
          <CardTitle className="mb-3 text-sm">📈 Транспортный поток</CardTitle>
          <ResponsiveContainer width="100%" height={180}>
            <AreaChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="t" tick={CHART_TICK} />
              <YAxis tick={CHART_TICK} />
              <Tooltip contentStyle={CHART_TOOLTIP} />
              <Legend wrapperStyle={{ fontSize: 11, color: 'hsl(var(--muted-foreground))' }} />
              <Area type="monotone" dataKey="cars" stackId="1" stroke="#63b3ed" fill="#63b3ed33" name="Авто" />
              <Area type="monotone" dataKey="trucks" stackId="1" stroke="#ed8936" fill="#ed893633" name="Грузов." />
              <Area type="monotone" dataKey="pedestrians" stackId="1" stroke="#b794f4" fill="#b794f433" name="Пешеходы" />
            </AreaChart>
          </ResponsiveContainer>
        </Card>

        {/* Wait time chart */}
        <Card className="min-w-[300px] flex-1 p-4">
          <CardTitle className="mb-3 text-sm">⏱ Время ожидания</CardTitle>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="t" tick={CHART_TICK} />
              <YAxis tick={CHART_TICK} />
              <Tooltip contentStyle={CHART_TOOLTIP} />
              <Legend wrapperStyle={{ fontSize: 11, color: 'hsl(var(--muted-foreground))' }} />
              <Line type="monotone" dataKey="waitCar" stroke="#63b3ed" dot={false} name="Авто (сек)" strokeWidth={2} />
              <Line type="monotone" dataKey="waitPed" stroke="#b794f4" dot={false} name="Пешеходы (сек)" strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </Card>

        {/* Throughput chart */}
        <Card className="min-w-[260px] flex-1 p-4">
          <CardTitle className="mb-3 text-sm">✅ Пропускная способность</CardTitle>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={chartData.slice(-20)}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="t" tick={CHART_TICK} />
              <YAxis tick={CHART_TICK} />
              <Tooltip contentStyle={CHART_TOOLTIP} />
              <Bar dataKey="throughput" fill="#68d391" name="Прошло" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>

      {/* System status */}
      <Card className="flex flex-wrap gap-4 px-5 py-3">
        <StatusDot label="Камера" status={system.camera_status || 'simulation'} />
        <StatusDot label="YOLO" status={system.yolo_status || 'simulation'} />
        <StatusDot label="Режим" value={mode} color={MODE_COLORS[mode]} />
        <StatusDot label="FPS" value={`${(system.camera_fps || 0).toFixed(0)}`} />
        <StatusDot label="Ошибок" value={system.error_count || 0} color={(system.error_count || 0) > 0 ? '#fc8181' : '#68d391'} />
      </Card>
    </div>
  )
}

function StatusDot({ label, status, value, color }) {
  const statusColor = {
    simulation: '#f6e05e', active: '#68d391', ok: '#68d391', connected: '#68d391', connecting: '#f6e05e',
    error: '#fc8181', unavailable: '#fc8181', no_signal: '#fc8181', disconnected: '#fc8181', unknown: '#718096',
  }[status] || color || '#68d391'

  return (
    <div className="flex items-center gap-1.5">
      <div className="h-1.5 w-1.5 rounded-full" style={{ background: statusColor }} />
      <span className="text-xs text-muted-foreground">{label}:</span>
      <span className="text-xs font-semibold">{value || status || '—'}</span>
    </div>
  )
}
