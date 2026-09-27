/**
 * Layout geometry shared by the constructor UI. Mirrors smart_intersection/layout.py (box size, lanes, roundabout,
 * road_rects / hits_road, signal stages); tests/test_frontend_geometry.py compares both implementations point by
 * point on every ready-made junction, so they cannot drift apart.
 */
export const ARMS = ['north', 'south', 'east', 'west']
export const OPPOSITE = { north: 'south', south: 'north', east: 'west', west: 'east' }
export const OUT = { north: [0, -1], south: [0, 1], east: [1, 0], west: [-1, 0] }
export const LANE_W = 4
export const BOX_MIN = 16
export const MAX_LANES = 4
export const MIN_ARM_EXTRA = 14
export const GRID = 2
export const MOVES = ['left', 'straight', 'right', 'uturn']

// object type -> footprint radius (m) at scale 1
export const SCENE_TYPES = {
  building: { radius: 5, label: 'Building', icon: '🏢' },
  house: { radius: 4, label: 'House', icon: '🏠' },
  tree: { radius: 0.8, label: 'Tree', icon: '🌳' },
  lamp: { radius: 0.6, label: 'Street lamp', icon: '💡' },
  bus_stop: { radius: 2.5, label: 'Bus stop', icon: '🚏' },
  bench: { radius: 1, label: 'Bench', icon: '🪑' },
  fence: { radius: 2, label: 'Fence', icon: '🚧' },
  kiosk: { radius: 1.8, label: 'Kiosk', icon: '🏪' },
}

// ---- arms, lanes, box

export const lanesIn = (a) => a.lanes_in ?? 1
export const lanesOut = (a) => a.lanes_out ?? 1
export const enabledArms = (layout) => ARMS.filter(a => layout.arms[a].enabled)

/** Unit vector to the driver's right for traffic entering from `arm`. */
export function rightVec(arm) {
  const [ox, oz] = OUT[arm]
  return [oz, -ox]                       // heading = (-ox, -oz); right = (-hz, hx)
}

/** The arm a vehicle ends up on after `move` (right-hand traffic). */
export function targetArm(arm, move) {
  if (move === 'straight') return OPPOSITE[arm]
  if (move === 'uturn') return arm
  const [rx, rz] = rightVec(arm)
  const s = move === 'right' ? 1 : -1
  return ARMS.find(a => OUT[a][0] === rx * s && OUT[a][1] === rz * s)
}

export const maxLanes = (layout) => Math.max(1, ...enabledArms(layout).map(a => Math.max(lanesIn(layout.arms[a]), lanesOut(layout.arms[a]))))

export function roundaboutDims(layout) {
  const ri = 10 + 2 * Math.min(maxLanes(layout), 2)
  return { island: ri, ring_center: ri + 2.5, outer: ri + 5, box: ri + 13 }
}

/** Half side of the central square: wide roads need a bigger junction. */
export function boxHalf(layout) {
  if (layout.junction === 'roundabout') return roundaboutDims(layout).box
  return Math.max(BOX_MIN, LANE_W * maxLanes(layout) + 8)
}

export const stopDist = (layout) => boxHalf(layout) + 5
export const minArmLength = (layout) => boxHalf(layout) + MIN_ARM_EXTRA

/** Asphalt extent of an arm across its axis (world x for north / south, world z for east / west). */
export function lateralSpan(layout, arm) {
  const a = layout.arms[arm]
  const [rx, rz] = rightVec(arm)
  const rU = arm === 'north' || arm === 'south' ? rx : rz
  const lin = LANE_W * lanesIn(a), lout = LANE_W * lanesOut(a)
  return rU < 0 ? [-lin, lout] : [-lout, lin]
}

export function crossingSpan(layout, arm) {
  const [lo, hi] = lateralSpan(layout, arm)
  return [lo - 2, hi + 2]
}

export const hasCrossing = (layout, arm) => {
  const a = layout.arms[arm]
  return a.enabled && a.crossing
}

/** Movements every inbound lane allows (default: straight only). */
export const laneTurns = (a) => (a.turns ? a.turns.map(t => [...t]) : Array.from({ length: lanesIn(a) }, () => ['straight']))

export function laneMoves(layout, arm, lane) {
  return (laneTurns(layout.arms[arm])[lane] ?? ['straight']).filter(m => m === 'straight' || layout.arms[targetArm(arm, m)].enabled)
}

export const turnsConflict = (layout, arm) =>
  Array.from({ length: lanesIn(layout.arms[arm]) }, (_, i) => laneMoves(layout, arm, i)).flat().some(m => m === 'left' || m === 'uturn')

export const compatible = (layout, a, b) =>
  a === b || (OPPOSITE[a] === b && !turnsConflict(layout, a) && !turnsConflict(layout, b))

/** Signal stages: NS / EW pairs, split into one stage per arm where turns cross the opposing flow. */
export function stages(layout) {
  const out = []
  for (const pair of [['north', 'south'], ['east', 'west']]) {
    const arms = pair.filter(a => layout.arms[a].enabled)
    if (arms.length === 2 && compatible(layout, arms[0], arms[1])) out.push(arms)
    else arms.forEach(a => out.push([a]))
  }
  return out
}

/** The classic north-south / east-west lamps cannot describe the signal plan (protected turn stages). */
export const isSplit = (layout) =>
  (layout.junction ?? 'signal') === 'signal' &&
  stages(layout).some(s => s.length === 1 && layout.arms[OPPOSITE[s[0]]].enabled)

/** Traffic light pole: just past the stop line, on the kerb at the driver's right. */
export function lightPole(layout, arm) {
  const B = boxHalf(layout)
  const [ox, oz] = OUT[arm]
  const [rx, rz] = rightVec(arm)
  const lat = LANE_W * lanesIn(layout.arms[arm]) + 3
  return [ox * (B + 6) + rx * lat, oz * (B + 6) + rz * lat]
}

/** Pedestrian signal poles at both ends of a crosswalk, facing the people waiting on each kerb. */
export function pedestrianLightPoles(layout, arm) {
  const B = boxHalf(layout)
  const [ox, oz] = OUT[arm]
  const [lo, hi] = crossingSpan(layout, arm)
  const center = B + 2.5
  const eastWestCrossing = arm === 'north' || arm === 'south'
  return [
    { pos: eastWestCrossing ? [lo - 1.5, oz * center] : [ox * center, lo - 1.5], rotation: eastWestCrossing ? Math.PI / 2 : 0 },
    { pos: eastWestCrossing ? [hi + 1.5, oz * center] : [ox * center, hi + 1.5], rotation: eastWestCrossing ? -Math.PI / 2 : Math.PI },
  ]
}

export function roadRects(layout) {
  const h = boxHalf(layout)
  const rects = [[-h, -h, h, h]]
  const [c0, c1] = [h + 1, h + 4]
  for (const arm of ARMS) {
    const a = layout.arms[arm]
    if (!a.enabled) continue
    const L = a.length_m
    const [lo, hi] = lateralSpan(layout, arm)
    const cross = hasCrossing(layout, arm)
    const [clo, chi] = crossingSpan(layout, arm)
    const mid = (clo + chi) / 2, hw = (chi - clo) / 2 + 3
    if (arm === 'north') { rects.push([lo, -L, hi, -h]); if (cross) rects.push([mid - hw, -c1, mid + hw, -c0]) }
    else if (arm === 'south') { rects.push([lo, h, hi, L]); if (cross) rects.push([mid - hw, c0, mid + hw, c1]) }
    else if (arm === 'east') { rects.push([h, lo, L, hi]); if (cross) rects.push([c0, mid - hw, c1, mid + hw]) }
    else { rects.push([-L, lo, -h, hi]); if (cross) rects.push([-c1, mid - hw, -c0, mid + hw]) }
  }
  return rects
}

export function hitsRoad(layout, x, z, radius) {
  for (const [x0, z0, x1, z1] of roadRects(layout)) {
    const dx = Math.max(x0 - x, 0, x - x1)
    const dz = Math.max(z0 - z, 0, z - z1)
    if (dx * dx + dz * dz < radius * radius) return true
  }
  return false
}

export const footprint = (obj) => SCENE_TYPES[obj.type].radius * (obj.scale ?? 1)

export const snap = (v, step = GRID) => Math.round(v / step) * step

/** Arm whose direction is closest to the point (used by the interactive spawn tools). */
export function nearestArm(x, z) {
  return Math.abs(x) > Math.abs(z) ? (x > 0 ? 'east' : 'west') : (z > 0 ? 'south' : 'north')
}

export const crossingId = (arm) => `PC-${arm[0].toUpperCase()}`

/** Next free id like "tree-7". */
export function nextId(layout, prefix) {
  const used = new Set([...layout.scenery.map(o => o.id), ...layout.cameras.map(c => c.id)])
  let n = 1
  while (used.has(`${prefix}-${n}`)) n++
  return `${prefix}-${n}`
}

export const BUILDING_COLORS = ['#7c8fb0', '#a78bfa', '#94a3b8', '#c08497', '#84a98c', '#d4a373']

// ---- virtual camera (pinhole): same maths as backend/vision/camera_model.py

const rad = (d) => (d * Math.PI) / 180

/** Compass yaw / downward pitch in degrees with the automatic aim (at the junction centre) applied. */
export function cameraAim(cam) {
  const dx = -cam.x, dz = -cam.z
  const dist = Math.hypot(dx, dz)
  const yaw = cam.yaw_deg ?? (dist > 1e-6 ? (Math.atan2(dx, -dz) * 180) / Math.PI : 0)
  const pitch = cam.pitch_deg ?? (Math.atan2(cam.height_m ?? 12, Math.max(dist, 1e-6)) * 180) / Math.PI
  return [((yaw % 360) + 360) % 360, Math.max(1, Math.min(90, pitch))]
}

/** Where the picture corners meet the ground (world x, z) for a camera with the given aspect ratio, limited to its range. */
export function cameraFootprint(cam, aspect = 4 / 3) {
  const [yaw, pitch] = cameraAim(cam)
  const ya = rad(yaw), pa = rad(pitch)
  const f = [Math.sin(ya) * Math.cos(pa), -Math.sin(pa), -Math.cos(ya) * Math.cos(pa)]
  const r = [Math.cos(ya), 0, Math.sin(ya)]
  const u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]]
  const tanH = Math.tan(rad(cam.fov_deg ?? 70) / 2)
  const out = []
  for (const [sx, sy] of [[-1, 1], [1, 1], [1, -1], [-1, -1]]) {
    const k = [0, 1, 2].map(i => f[i] + r[i] * sx * tanH + u[i] * sy * (tanH / aspect))
    const n = Math.hypot(...k)
    const d = k.map(v => v / n)
    const range = cam.radius_m ?? 90
    let dist = range
    if (d[1] < -1e-6) dist = Math.min(dist, Math.hypot(d[0], d[2]) * ((cam.height_m ?? 12) / -d[1]))
    const hd = Math.hypot(d[0], d[2]) || 1e-9
    out.push([cam.x + (d[0] / hd) * dist, cam.z + (d[2] / hd) * dist])
  }
  return out
}

/** Default virtual camera mounted beside one approach and aimed across that approach. */
export const defaultCamera = (layout) => ({
  id: 'CAM-01', x: -boxHalf(layout) - 14, z: 0, height_m: 12, fov_deg: 55, radius_m: 75, yaw_deg: null, pitch_deg: null, enabled: true,
})
