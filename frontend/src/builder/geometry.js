/**
 * Layout geometry shared by the constructor UI. Mirrors smart_intersection/layout.py (hits_road / road_rects);
 * tests/test_frontend_geometry.py compares both implementations point by point, so they cannot drift apart.
 */
export const ARMS = ['north', 'south', 'east', 'west']
export const OPPOSITE = { north: 'south', south: 'north', east: 'west', west: 'east' }
export const BOX_HALF = 16
export const ASPHALT_HALF = 4
export const CROSSWALK_BAND = [17, 20]
export const CROSSWALK_HALF_WIDTH = 9
export const GRID = 2

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

export function roadRects(layout) {
  const h = BOX_HALF
  const rects = [[-h, -h, h, h]]
  const [c0, c1] = CROSSWALK_BAND
  const w = CROSSWALK_HALF_WIDTH
  for (const arm of ARMS) {
    const a = layout.arms[arm]
    if (!a.enabled) continue
    const L = a.length_m
    if (arm === 'north') { rects.push([-ASPHALT_HALF, -L, ASPHALT_HALF, -h]); if (a.crossing) rects.push([-w, -c1, w, -c0]) }
    else if (arm === 'south') { rects.push([-ASPHALT_HALF, h, ASPHALT_HALF, L]); if (a.crossing) rects.push([-w, c0, w, c1]) }
    else if (arm === 'east') { rects.push([h, -ASPHALT_HALF, L, ASPHALT_HALF]); if (a.crossing) rects.push([c0, -w, c1, w]) }
    else { rects.push([-L, -ASPHALT_HALF, -h, ASPHALT_HALF]); if (a.crossing) rects.push([-c1, -w, -c0, w]) }
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
