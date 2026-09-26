import { useState, useEffect, useRef } from 'react'
import { useWebSocket } from '../hooks/useWebSocket'
import { controlApi, lightsApi } from '../api/client'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, AreaChart, Area, BarChart, Bar, Legend
} from 'recharts'

const LIGHT_COLORS = { RED: '#fc8181', YELLOW: '#f6e05e', GREEN: '#68d391', FLASHING_YELLOW: '#f6e05e', OFF: '#4a5568' }
const MODE_COLORS = { AUTO: '#68d391', MANUAL: '#63b3ed', FAILSAFE: '#fc8181' }
const CONGESTION_COLORS = { CLEAR: '#68d391', MODERATE: '#f6e05e', CONGESTED: '#ed8936', GRIDLOCK: '#fc8181' }

function TrafficLightBulb({ state, size = 28 }) {
  const states = ['RED', 'YELLOW', 'GREEN']
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, background: '#1a202c', padding: 8, borderRadius: 8, border: '1px solid #2d3748' }}>
      {states.map(s => (
        <div key={s} style={{
          width: size, height: size, borderRadius: '50%',
          background: state === s ? LIGHT_COLORS[s] : '#2d3748',
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
      style={{
        padding: '8px 20px', borderRadius: 6, cursor: 'pointer', fontWeight: 700,
        fontSize: 13, border: `2px solid ${MODE_COLORS[mode]}`,
        background: active ? MODE_COLORS[mode] + '33' : 'transparent',
        color: active ? MODE_COLORS[mode] : '#a0aec0',
        transition: 'all 0.15s',
      }}
      onClick={() => onClick(mode)}
    >
      {mode}
    </button>
  )
}

function StatCard({ label, value, unit, color }) {
  return (
    <div style={{ background: '#1a1d27', border: '1px solid #2d3748', borderRadius: 8, padding: '14px 18px', minWidth: 130 }}>
      <div style={{ color: '#718096', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 }}>{label}</div>
      <div style={{ color: color || '#e2e8f0', fontSize: 26, fontWeight: 700 }}>{value}</div>
      {unit && <div style={{ color: '#718096', fontSize: 11 }}>{unit}</div>}
    </div>
  )
}

export default function Dashboard() {
  const { connected, lastMessage, send } = useWebSocket()
  const [wsData, setWsData] = useState(null)
  const [chartData, setChartData] = useState([])
  const [mode, setMode] = useState('AUTO')
  const [failsafeReason, setFailsafeReason] = useState(null)
  const [lights, setLights] = useState([])
  const [simRunning, setSimRunning] = useState(false)

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

  const traffic = wsData?.metrics?.traffic || {}
  const system = wsData?.metrics?.system || {}
  const extra = wsData?.metrics?.extra || {}

  const s = {
    page: { minHeight: 'calc(100vh - 56px)', background: '#0f1117', padding: 16, display: 'flex', flexDirection: 'column', gap: 12 },
    row: { display: 'flex', gap: 12, flexWrap: 'wrap' },
    card: { background: '#1a1d27', border: '1px solid #2d3748', borderRadius: 10, padding: 16 },
    cardTitle: { fontWeight: 700, fontSize: 14, color: '#e2e8f0', marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8 },
    section: { display: 'flex', gap: 12, flexWrap: 'wrap' },
  }

  return (
    <div style={s.page}>
      {/* Top status bar */}
      <div style={{ ...s.card, display: 'flex', alignItems: 'center', gap: 16, padding: '10px 20px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <div style={{ width: 8, height: 8, borderRadius: '50%', background: connected ? '#68d391' : '#fc8181' }} />
          <span style={{ fontSize: 13, color: connected ? '#68d391' : '#fc8181' }}>
            {connected ? 'Подключено' : 'Отключено'}
          </span>
        </div>
        <div style={{ marginLeft: 16, display: 'flex', gap: 8 }}>
          <ModeButton mode="AUTO" current={mode} onClick={handleModeChange} />
          <ModeButton mode="MANUAL" current={mode} onClick={handleModeChange} />
          <ModeButton mode="FAILSAFE" current={mode} onClick={handleModeChange} />
        </div>
        {failsafeReason && (
          <div style={{ marginLeft: 16, background: '#742a2a33', border: '1px solid #fc8181', borderRadius: 6, padding: '4px 12px', color: '#fc8181', fontSize: 13 }}>
            ⚠ FAILSAFE: {failsafeReason}
          </div>
        )}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
          <button style={{ padding: '5px 12px', borderRadius: 5, cursor: 'pointer', fontSize: 12, background: simRunning ? '#742a2a44' : '#276749', color: '#fff', border: 'none', fontWeight: 600 }}
            onClick={() => handleSimControl(simRunning ? 'stop' : 'start')}>
            {simRunning ? '⏹ Стоп симуляции' : '▶ Запуск симуляции'}
          </button>
          <button style={{ padding: '5px 12px', borderRadius: 5, cursor: 'pointer', fontSize: 12, background: '#2d3748', color: '#a0aec0', border: 'none' }}
            onClick={() => handleSimControl('reset')}>
            ↺ Сброс
          </button>
        </div>
      </div>

      <div style={s.row}>
        {/* Traffic lights panel */}
        <div style={{ ...s.card, minWidth: 280, flex: '0 0 auto' }}>
          <div style={s.cardTitle}>🚦 Светофоры</div>
          {lights.length === 0 && (
            <div style={{ color: '#718096', fontSize: 13 }}>Нет светофоров — создайте их в Конструкторе</div>
          )}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            {lights.map(light => (
              <div key={light.id} style={{ display: 'flex', alignItems: 'center', gap: 12, background: '#131722', borderRadius: 8, padding: '8px 12px' }}>
                <TrafficLightBulb state={light.state} size={20} />
                <div style={{ flex: 1 }}>
                  <div style={{ fontWeight: 600, fontSize: 13, color: '#e2e8f0' }}>{light.id}</div>
                  <div style={{ fontSize: 11, color: '#718096' }}>
                    {light.direction || '—'} · фаза {light.phase_index + 1}
                  </div>
                  <div style={{ fontSize: 11, color: '#718096' }}>
                    Осталось: {Math.round(light.time_remaining)}с
                  </div>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                  <div style={{
                    padding: '3px 8px', borderRadius: 4, fontSize: 11, fontWeight: 700,
                    background: LIGHT_COLORS[light.state] + '22', color: LIGHT_COLORS[light.state]
                  }}>{light.state}</div>
                </div>
                {mode === 'MANUAL' && (
                  <div style={{ display: 'flex', gap: 3 }}>
                    {['RED', 'YELLOW', 'GREEN'].map(st => (
                      <button key={st}
                        style={{ width: 14, height: 14, borderRadius: '50%', background: LIGHT_COLORS[st], border: light.state === st ? '2px solid #fff' : '2px solid transparent', cursor: 'pointer' }}
                        onClick={() => handleManualLight(light.id, st)} />
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        {/* Stats */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 12 }}>
          {/* KPI row */}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
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
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {extra.congestion_level && (
              <div style={{ padding: '4px 12px', borderRadius: 6, fontSize: 12, fontWeight: 600, background: CONGESTION_COLORS[extra.congestion_level] + '22', color: CONGESTION_COLORS[extra.congestion_level], border: `1px solid ${CONGESTION_COLORS[extra.congestion_level]}44` }}>
                Трафик: {extra.congestion_level}
              </div>
            )}
            {extra.pedestrian_risk && (
              <div style={{ padding: '4px 12px', borderRadius: 6, fontSize: 12, fontWeight: 600, background: '#b794f422', color: '#b794f4', border: '1px solid #b794f444' }}>
                Риск пешеходов: {extra.pedestrian_risk}
              </div>
            )}
            <div style={{ padding: '4px 12px', borderRadius: 6, fontSize: 12, background: '#2d3748', color: '#a0aec0' }}>
              Переключений: {system.phase_switches || 0}
            </div>
            <div style={{ padding: '4px 12px', borderRadius: 6, fontSize: 12, background: '#2d3748', color: '#a0aec0' }}>
              Аптайм: {Math.floor((system.uptime_seconds || 0) / 60)}м {Math.round((system.uptime_seconds || 0) % 60)}с
            </div>
          </div>
        </div>
      </div>

      {/* Charts row */}
      <div style={s.row}>
        {/* Vehicle count chart */}
        <div style={{ ...s.card, flex: 1, minWidth: 300 }}>
          <div style={s.cardTitle}>📈 Транспортный поток</div>
          <ResponsiveContainer width="100%" height={180}>
            <AreaChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3748" />
              <XAxis dataKey="t" tick={{ fill: '#718096', fontSize: 10 }} />
              <YAxis tick={{ fill: '#718096', fontSize: 10 }} />
              <Tooltip contentStyle={{ background: '#1a1d27', border: '1px solid #4a5568', color: '#e2e8f0', fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 11, color: '#a0aec0' }} />
              <Area type="monotone" dataKey="cars" stackId="1" stroke="#63b3ed" fill="#63b3ed33" name="Авто" />
              <Area type="monotone" dataKey="trucks" stackId="1" stroke="#ed8936" fill="#ed893633" name="Грузов." />
              <Area type="monotone" dataKey="pedestrians" stackId="1" stroke="#b794f4" fill="#b794f433" name="Пешеходы" />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Wait time chart */}
        <div style={{ ...s.card, flex: 1, minWidth: 300 }}>
          <div style={s.cardTitle}>⏱ Время ожидания</div>
          <ResponsiveContainer width="100%" height={180}>
            <LineChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3748" />
              <XAxis dataKey="t" tick={{ fill: '#718096', fontSize: 10 }} />
              <YAxis tick={{ fill: '#718096', fontSize: 10 }} />
              <Tooltip contentStyle={{ background: '#1a1d27', border: '1px solid #4a5568', color: '#e2e8f0', fontSize: 12 }} />
              <Legend wrapperStyle={{ fontSize: 11, color: '#a0aec0' }} />
              <Line type="monotone" dataKey="waitCar" stroke="#63b3ed" dot={false} name="Авто (сек)" strokeWidth={2} />
              <Line type="monotone" dataKey="waitPed" stroke="#b794f4" dot={false} name="Пешеходы (сек)" strokeWidth={2} />
            </LineChart>
          </ResponsiveContainer>
        </div>

        {/* Throughput chart */}
        <div style={{ ...s.card, flex: 1, minWidth: 260 }}>
          <div style={s.cardTitle}>✅ Пропускная способность</div>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={chartData.slice(-20)}>
              <CartesianGrid strokeDasharray="3 3" stroke="#2d3748" />
              <XAxis dataKey="t" tick={{ fill: '#718096', fontSize: 10 }} />
              <YAxis tick={{ fill: '#718096', fontSize: 10 }} />
              <Tooltip contentStyle={{ background: '#1a1d27', border: '1px solid #4a5568', color: '#e2e8f0', fontSize: 12 }} />
              <Bar dataKey="throughput" fill="#68d391" name="Прошло" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* System status */}
      <div style={{ ...s.card, display: 'flex', gap: 16, flexWrap: 'wrap', padding: '12px 20px' }}>
        <StatusDot label="Камера" status={system.camera_status || 'simulation'} />
        <StatusDot label="YOLO" status={system.yolo_status || 'simulation'} />
        <StatusDot label="Режим" value={mode} color={MODE_COLORS[mode]} />
        <StatusDot label="FPS" value={`${(system.camera_fps || 0).toFixed(0)}`} />
        <StatusDot label="Ошибок" value={system.error_count || 0} color={(system.error_count || 0) > 0 ? '#fc8181' : '#68d391'} />
      </div>
    </div>
  )
}

function StatusDot({ label, status, value, color }) {
  const statusColor = {
    simulation: '#f6e05e', active: '#68d391', ok: '#68d391',
    error: '#fc8181', unavailable: '#fc8181', unknown: '#718096',
  }[status] || color || '#68d391'

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div style={{ width: 7, height: 7, borderRadius: '50%', background: statusColor }} />
      <span style={{ color: '#718096', fontSize: 12 }}>{label}:</span>
      <span style={{ color: '#e2e8f0', fontSize: 12, fontWeight: 600 }}>
        {value || status || '—'}
      </span>
    </div>
  )
}
