import { useState, useRef, useCallback, useEffect } from 'react'
import { intersectionApi } from '../api/client'

const CELL = 40
const COLS = 20
const ROWS = 20

const TOOLS = [
  { id: 'select', label: '↖ Выбор', icon: '↖', group: 'tools' },
  { id: 'delete', label: '✕ Удалить', icon: '✕', group: 'tools' },
  { id: 'car_lane', label: '🚗 Полоса', icon: '🚗', group: 'roads', laneType: 'car' },
  { id: 'bus_lane', label: '🚌 Авт. полоса', icon: '🚌', group: 'roads', laneType: 'bus' },
  { id: 'tram', label: '🚃 Трамвай', icon: '🚃', group: 'roads', laneType: 'tram' },
  { id: 'bike', label: '🚲 Вело', icon: '🚲', group: 'roads', laneType: 'bike' },
  { id: 'reversible', label: '↔ Реверс', icon: '↔', group: 'roads', laneType: 'reversible' },
  { id: 'pedestrian_crossing', label: '🚶 Переход', icon: '🚶', group: 'infra' },
  { id: 'traffic_light', label: '🚦 Светофор', icon: '🚦', group: 'infra' },
  { id: 'camera', label: '📷 Камера', icon: '📷', group: 'infra' },
  { id: 'zone', label: '📍 Зона', icon: '📍', group: 'infra' },
]

const OBJECT_COLORS = {
  car: '#4299e1', bus: '#48bb78', tram: '#ed8936',
  bike: '#9f7aea', reversible: '#fc8181', pedestrian: '#f6e05e',
  traffic_light: '#f6ad55', camera: '#76e4f7', zone: '#fbb6ce',
  pedestrian_crossing: '#b794f4',
}

const DIRECTION_OPTIONS = ['north', 'south', 'east', 'west', 'north_east', 'north_west', 'south_east', 'south_west']

function cellId(col, row) { return `${col}-${row}` }

let nextId = 1
function genId(prefix) { return `${prefix}-${nextId++}` }

export default function Constructor() {
  const [objects, setObjects] = useState([]) // {id, type, cells:[[col,row]], laneType?, direction?, props}
  const [selectedTool, setSelectedTool] = useState('select')
  const [selectedObj, setSelectedObj] = useState(null)
  const [dragging, setDragging] = useState(false)
  const [dragStart, setDragStart] = useState(null)
  const [dragCells, setDragCells] = useState([])
  const [status, setStatus] = useState('')
  const canvasRef = useRef(null)

  const getObjAtCell = useCallback((col, row) => {
    return objects.find(o => o.cells.some(([c, r]) => c === col && r === row))
  }, [objects])

  const handleMouseDown = (col, row, e) => {
    e.preventDefault()
    const tool = selectedTool
    if (tool === 'select') {
      const obj = getObjAtCell(col, row)
      setSelectedObj(obj || null)
      return
    }
    if (tool === 'delete') {
      const obj = getObjAtCell(col, row)
      if (obj) {
        setObjects(prev => prev.filter(o => o.id !== obj.id))
        setSelectedObj(null)
      }
      return
    }
    setDragging(true)
    setDragStart([col, row])
    setDragCells([[col, row]])
  }

  const handleMouseEnter = (col, row) => {
    if (!dragging || !dragStart) return
    const [sc, sr] = dragStart
    const cells = []
    const minC = Math.min(sc, col), maxC = Math.max(sc, col)
    const minR = Math.min(sr, row), maxR = Math.max(sr, row)
    for (let c = minC; c <= maxC; c++)
      for (let r = minR; r <= maxR; r++)
        cells.push([c, r])
    setDragCells(cells)
  }

  const handleMouseUp = () => {
    if (!dragging || dragCells.length === 0) { setDragging(false); return }
    const tool = selectedTool
    const toolDef = TOOLS.find(t => t.id === tool)

    let newObj = null
    if (tool === 'traffic_light') {
      const [c, r] = dragCells[0]
      newObj = { id: genId('TL'), type: 'traffic_light', cells: [[c, r]],
        props: { direction: 'north', laneIds: [], priority: 1.0, conflictIds: [],
          phases: [
            { state: 'RED', duration: 30 }, { state: 'YELLOW', duration: 3 },
            { state: 'GREEN', duration: 30 }, { state: 'YELLOW', duration: 3 },
          ]
        }
      }
    } else if (tool === 'pedestrian_crossing') {
      newObj = { id: genId('PC'), type: 'pedestrian_crossing', cells: dragCells,
        props: { trafficLightId: null }
      }
    } else if (tool === 'camera') {
      const [c, r] = dragCells[0]
      newObj = { id: genId('CAM'), type: 'camera', cells: [[c, r]],
        props: { fovAngle: 90, zoneIds: [] }
      }
    } else if (tool === 'zone') {
      newObj = { id: genId('ZONE'), type: 'zone', cells: dragCells,
        props: { zoneType: 'vehicle' }
      }
    } else if (toolDef?.group === 'roads') {
      newObj = { id: genId(tool.toUpperCase().slice(0, 3)), type: 'lane',
        cells: dragCells, laneType: toolDef.laneType || 'car',
        props: { direction: 'north', priority: 1.0, speedLimit: 60 }
      }
    }

    if (newObj) {
      setObjects(prev => [...prev, newObj])
      setSelectedObj(newObj)
    }
    setDragging(false)
    setDragStart(null)
    setDragCells([])
  }

  const updateObjProp = (key, value) => {
    if (!selectedObj) return
    setObjects(prev => prev.map(o =>
      o.id === selectedObj.id
        ? { ...o, props: { ...o.props, [key]: value } }
        : o
    ))
    setSelectedObj(prev => ({ ...prev, props: { ...prev.props, [key]: value } }))
  }

  const buildConfig = () => {
    const lanes = [], lights = [], crossings = [], cameras = [], zones = [], trams = []
    for (const obj of objects) {
      if (obj.type === 'lane') {
        const cells = obj.cells
        lanes.push({
          id: obj.id, type: obj.laneType,
          direction: obj.props.direction || 'north',
          start: { col: cells[0][0], row: cells[0][1] },
          end: { col: cells[cells.length - 1][0], row: cells[cells.length - 1][1] },
          priority: obj.props.priority || 1.0,
          speed_limit: obj.props.speedLimit || 60,
        })
        if (obj.laneType === 'tram') {
          trams.push({
            id: obj.id + '_track', direction: obj.props.direction,
            start: { col: cells[0][0], row: cells[0][1] },
            end: { col: cells[cells.length - 1][0], row: cells[cells.length - 1][1] },
          })
        }
      } else if (obj.type === 'traffic_light') {
        const [c, r] = obj.cells[0]
        lights.push({
          id: obj.id, position: { col: c, row: r },
          direction: obj.props.direction || 'north',
          lane_ids: obj.props.laneIds || [],
          phase_sequence: obj.props.phases,
          priority: obj.props.priority || 1.0,
          conflict_ids: obj.props.conflictIds || [],
        })
      } else if (obj.type === 'pedestrian_crossing') {
        const cells = obj.cells
        crossings.push({
          id: obj.id,
          start: { col: cells[0][0], row: cells[0][1] },
          end: { col: cells[cells.length - 1][0], row: cells[cells.length - 1][1] },
          traffic_light_id: obj.props.trafficLightId || null,
        })
      } else if (obj.type === 'camera') {
        const [c, r] = obj.cells[0]
        cameras.push({
          id: obj.id, position: { col: c, row: r },
          fov_angle: obj.props.fovAngle || 90,
          zone_ids: obj.props.zoneIds || [],
        })
      } else if (obj.type === 'zone') {
        const cells = obj.cells
        zones.push({
          id: obj.id, zone_type: obj.props.zoneType || 'vehicle',
          top_left: { col: cells[0][0], row: cells[0][1] },
          bottom_right: { col: cells[cells.length - 1][0], row: cells[cells.length - 1][1] },
        })
      }
    }
    return {
      id: 'main', name: 'Smart Intersection',
      grid_cols: COLS, grid_rows: ROWS, cell_size: CELL,
      lanes, traffic_lights: lights, pedestrian_crossings: crossings,
      cameras, detection_zones: zones, tram_tracks: trams,
      direction_priorities: { north: 1.0, south: 1.0, east: 1.0, west: 1.0, pedestrian: 1.3 }
    }
  }

  const handleSave = async () => {
    const config = buildConfig()
    try {
      await intersectionApi.save(config)
      setStatus('✓ Конфигурация сохранена')
      setTimeout(() => setStatus(''), 3000)
    } catch (e) {
      setStatus('✕ Ошибка сохранения')
    }
  }

  const handleLoad = async () => {
    try {
      const { data } = await intersectionApi.get()
      if (!data.lanes && !data.traffic_lights) return
      const loaded = []
      for (const l of data.lanes || []) {
        loaded.push({
          id: l.id, type: 'lane', laneType: l.type,
          cells: [[l.start.col, l.start.row], [l.end.col, l.end.row]],
          props: { direction: l.direction, priority: l.priority, speedLimit: l.speed_limit }
        })
      }
      for (const tl of data.traffic_lights || []) {
        loaded.push({
          id: tl.id, type: 'traffic_light',
          cells: [[tl.position.col, tl.position.row]],
          props: { direction: tl.direction, laneIds: tl.lane_ids,
            priority: tl.priority, conflictIds: tl.conflict_ids,
            phases: tl.phase_sequence }
        })
      }
      for (const pc of data.pedestrian_crossings || []) {
        loaded.push({
          id: pc.id, type: 'pedestrian_crossing',
          cells: [[pc.start.col, pc.start.row], [pc.end.col, pc.end.row]],
          props: { trafficLightId: pc.traffic_light_id }
        })
      }
      setObjects(loaded)
      setStatus('✓ Конфигурация загружена')
      setTimeout(() => setStatus(''), 3000)
    } catch (e) {
      setStatus('✕ Нет сохранённой конфигурации')
    }
  }

  const handleClear = () => {
    setObjects([])
    setSelectedObj(null)
    setStatus('Холст очищен')
    setTimeout(() => setStatus(''), 2000)
  }

  // Build cell map for rendering
  const cellMap = {}
  for (const obj of objects) {
    for (const [c, r] of obj.cells) {
      cellMap[cellId(c, r)] = obj
    }
  }
  const dragMap = {}
  for (const [c, r] of dragCells) {
    dragMap[cellId(c, r)] = true
  }

  const s = {
    page: { display: 'flex', height: 'calc(100vh - 56px)', overflow: 'hidden', background: '#0f1117' },
    sidebar: { width: 200, background: '#1a1d27', borderRight: '1px solid #2d3748', padding: 12, display: 'flex', flexDirection: 'column', gap: 4, overflowY: 'auto' },
    groupLabel: { color: '#718096', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', padding: '8px 4px 4px', letterSpacing: 1 },
    toolBtn: (active) => ({
      display: 'flex', alignItems: 'center', gap: 8,
      padding: '8px 10px', borderRadius: 6, cursor: 'pointer', fontSize: 13,
      background: active ? '#2b6cb0' : 'transparent',
      color: active ? '#fff' : '#a0aec0',
      border: active ? '1px solid #3182ce' : '1px solid transparent',
      transition: 'all 0.15s',
    }),
    main: { flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' },
    toolbar: { display: 'flex', gap: 8, padding: '8px 16px', background: '#1a1d27', borderBottom: '1px solid #2d3748', alignItems: 'center' },
    btn: (color) => ({
      padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
      fontWeight: 600, fontSize: 13, background: color || '#2d3748', color: '#fff',
      transition: 'opacity 0.15s',
    }),
    canvasWrap: { flex: 1, overflow: 'auto', padding: 16 },
    grid: { display: 'grid', gridTemplateColumns: `repeat(${COLS}, ${CELL}px)`, gap: 0, userSelect: 'none' },
    cell: (obj, isDrag, isSelected) => ({
      width: CELL, height: CELL,
      border: '1px solid #1a2035',
      background: isDrag ? '#2b6cb055'
        : obj ? (OBJECT_COLORS[obj.laneType || obj.type] + '55')
        : '#131722',
      cursor: selectedTool === 'select' ? 'pointer' : 'crosshair',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontSize: 16, position: 'relative',
      outline: isSelected ? '2px solid #63b3ed' : 'none',
      transition: 'background 0.05s',
    }),
    propPanel: { width: 260, background: '#1a1d27', borderLeft: '1px solid #2d3748', padding: 16, overflowY: 'auto' },
    propTitle: { fontWeight: 700, fontSize: 14, color: '#e2e8f0', marginBottom: 12 },
    propRow: { marginBottom: 12 },
    label: { display: 'block', color: '#a0aec0', fontSize: 12, marginBottom: 4 },
    input: { width: '100%', background: '#2d3748', border: '1px solid #4a5568', borderRadius: 4, color: '#e2e8f0', padding: '6px 8px', fontSize: 13 },
    select: { width: '100%', background: '#2d3748', border: '1px solid #4a5568', borderRadius: 4, color: '#e2e8f0', padding: '6px 8px', fontSize: 13 },
    badge: (color) => ({ display: 'inline-block', padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 600, background: color + '33', color: color, border: `1px solid ${color}55` }),
    statusBar: { height: 28, background: '#1a1d27', borderTop: '1px solid #2d3748', display: 'flex', alignItems: 'center', padding: '0 16px', fontSize: 12, color: '#68d391' },
  }

  const groups = ['tools', 'roads', 'infra']
  const groupLabels = { tools: 'Инструменты', roads: 'Дороги', infra: 'Объекты' }

  return (
    <div style={s.page}>
      {/* Palette */}
      <aside style={s.sidebar}>
        {groups.map(g => (
          <div key={g}>
            <div style={s.groupLabel}>{groupLabels[g]}</div>
            {TOOLS.filter(t => t.group === g).map(tool => (
              <div key={tool.id} style={s.toolBtn(selectedTool === tool.id)}
                onClick={() => setSelectedTool(tool.id)}>
                <span>{tool.icon}</span>
                <span>{tool.label}</span>
              </div>
            ))}
          </div>
        ))}
      </aside>

      {/* Main area */}
      <main style={s.main}>
        <div style={s.toolbar}>
          <button style={s.btn('#2b6cb0')} onClick={handleLoad}>⬆ Загрузить</button>
          <button style={s.btn('#276749')} onClick={handleSave}>💾 Сохранить</button>
          <button style={s.btn('#742a2a')} onClick={handleClear}>🗑 Очистить</button>
          <span style={{ marginLeft: 'auto', fontSize: 12, color: '#718096' }}>
            {objects.length} объектов | {objects.filter(o=>o.type==='traffic_light').length} светофоров
          </span>
        </div>

        <div style={s.canvasWrap}>
          <div style={s.grid}
            onMouseLeave={() => { if (dragging) handleMouseUp() }}>
            {Array.from({ length: ROWS }, (_, r) =>
              Array.from({ length: COLS }, (_, c) => {
                const obj = cellMap[cellId(c, r)]
                const isDrag = dragMap[cellId(c, r)]
                const isSelected = selectedObj && obj?.id === selectedObj.id
                const icon = obj ? (
                  obj.type === 'traffic_light' ? '🚦'
                  : obj.type === 'pedestrian_crossing' ? '🚶'
                  : obj.type === 'camera' ? '📷'
                  : obj.type === 'zone' ? '📍'
                  : obj.laneType === 'bus' ? '🚌'
                  : obj.laneType === 'tram' ? '🚃'
                  : obj.laneType === 'bike' ? '🚲'
                  : obj.laneType === 'reversible' ? '↔'
                  : '🚗'
                ) : null
                // Only show icon on first cell of object
                const firstCell = obj?.cells[0]
                const showIcon = obj && firstCell && firstCell[0] === c && firstCell[1] === r

                return (
                  <div key={cellId(c, r)} style={s.cell(obj, isDrag, isSelected)}
                    onMouseDown={(e) => handleMouseDown(c, r, e)}
                    onMouseEnter={() => handleMouseEnter(c, r)}
                    onMouseUp={handleMouseUp}>
                    {showIcon && <span title={obj.id}>{icon}</span>}
                  </div>
                )
              })
            )}
          </div>
        </div>

        <div style={s.statusBar}>{status || `Инструмент: ${TOOLS.find(t=>t.id===selectedTool)?.label}`}</div>
      </main>

      {/* Properties panel */}
      {selectedObj && (
        <aside style={s.propPanel}>
          <div style={s.propTitle}>
            {selectedObj.type === 'lane' ? '🚗 Полоса' : selectedObj.type === 'traffic_light' ? '🚦 Светофор' : selectedObj.type === 'pedestrian_crossing' ? '🚶 Переход' : '📦 Объект'}
          </div>
          <div style={s.propRow}>
            <span style={s.badge(OBJECT_COLORS[selectedObj.laneType || selectedObj.type] || '#718096')}>
              {selectedObj.id}
            </span>
          </div>

          {selectedObj.type === 'lane' && (
            <>
              <div style={s.propRow}>
                <label style={s.label}>Направление</label>
                <select style={s.select} value={selectedObj.props?.direction || 'north'}
                  onChange={e => updateObjProp('direction', e.target.value)}>
                  {DIRECTION_OPTIONS.map(d => <option key={d} value={d}>{d}</option>)}
                </select>
              </div>
              <div style={s.propRow}>
                <label style={s.label}>Приоритет (0.5–2.0)</label>
                <input style={s.input} type="number" min={0.5} max={2} step={0.1}
                  value={selectedObj.props?.priority || 1.0}
                  onChange={e => updateObjProp('priority', parseFloat(e.target.value))} />
              </div>
              <div style={s.propRow}>
                <label style={s.label}>Скоростной лимит (км/ч)</label>
                <input style={s.input} type="number" min={10} max={120} step={10}
                  value={selectedObj.props?.speedLimit || 60}
                  onChange={e => updateObjProp('speedLimit', parseInt(e.target.value))} />
              </div>
            </>
          )}

          {selectedObj.type === 'traffic_light' && (
            <>
              <div style={s.propRow}>
                <label style={s.label}>Направление</label>
                <select style={s.select} value={selectedObj.props?.direction || 'north'}
                  onChange={e => updateObjProp('direction', e.target.value)}>
                  {DIRECTION_OPTIONS.map(d => <option key={d} value={d}>{d}</option>)}
                </select>
              </div>
              <div style={s.propRow}>
                <label style={s.label}>Приоритет (0.5–2.0)</label>
                <input style={s.input} type="number" min={0.5} max={2} step={0.1}
                  value={selectedObj.props?.priority || 1.0}
                  onChange={e => updateObjProp('priority', parseFloat(e.target.value))} />
              </div>
              <div style={{ marginTop: 12, color: '#a0aec0', fontSize: 12 }}>Фазы:</div>
              {(selectedObj.props?.phases || []).map((phase, i) => (
                <div key={i} style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                  <select style={{ ...s.select, flex: 1 }}
                    value={phase.state}
                    onChange={e => {
                      const phases = [...(selectedObj.props?.phases || [])]
                      phases[i] = { ...phases[i], state: e.target.value }
                      updateObjProp('phases', phases)
                    }}>
                    <option value="RED">RED</option>
                    <option value="YELLOW">YELLOW</option>
                    <option value="GREEN">GREEN</option>
                  </select>
                  <input style={{ ...s.input, width: 60 }} type="number" min={1} max={120}
                    value={phase.duration}
                    onChange={e => {
                      const phases = [...(selectedObj.props?.phases || [])]
                      phases[i] = { ...phases[i], duration: parseInt(e.target.value) || 1 }
                      updateObjProp('phases', phases)
                    }} />
                  <span style={{ color: '#718096', fontSize: 11, alignSelf: 'center' }}>с</span>
                </div>
              ))}
            </>
          )}

          {selectedObj.type === 'pedestrian_crossing' && (
            <div style={s.propRow}>
              <label style={s.label}>ID светофора (для связки)</label>
              <input style={s.input} type="text"
                value={selectedObj.props?.trafficLightId || ''}
                onChange={e => updateObjProp('trafficLightId', e.target.value || null)} />
            </div>
          )}

          <div style={{ marginTop: 16 }}>
            <button style={{ ...s.btn('#742a2a'), width: '100%' }}
              onClick={() => {
                setObjects(prev => prev.filter(o => o.id !== selectedObj.id))
                setSelectedObj(null)
              }}>
              ✕ Удалить объект
            </button>
          </div>
        </aside>
      )}
    </div>
  )
}
