/**
 * RoadSystem — the streets of a layout: asphalt, kerbs, lane lines, turn arrows, stop lines, crosswalks, bus lanes,
 * tram rails, the ring and island of a roundabout, and barriers where a straight route ends without a road.
 *
 * All geometry comes from builder/geometry.js (box size, lane spans), which mirrors the simulation service, so the picture
 * and the vehicles always agree. Flat shapes are merged into one mesh per layout (a wide junction has hundreds of them).
 */
import { useMemo } from 'react'
import { DoubleSide, BufferGeometry, Float32BufferAttribute, Color } from 'three'
import { ARMS, OPPOSITE, OUT, LANE_W, boxHalf, stopDist, lateralSpan, crossingSpan, hasCrossing, rightVec, laneMoves,
         roundaboutDims, lanesIn, lanesOut } from '../../builder/geometry'

const ASPHALT = '#555555', KERB = '#9ca3af', WHITE = '#ffffff', YELLOW = '#facc15'
const rect = (x0, z0, x1, z1, y, color) => ({ pts: [[x0, z0], [x1, z0], [x1, z1], [x0, z1]], y, color })
const disc = (r, y, color, n = 64) => ({ pts: Array.from({ length: n }, (_, i) => [r * Math.cos((2 * Math.PI * i) / n), r * Math.sin((2 * Math.PI * i) / n)]), y, color })

/** World point at `dist` from the centre along an arm, `lat` = world coordinate across the arm axis. */
const armPt = (arm, dist, lat) => (arm === 'north' ? [lat, -dist] : arm === 'south' ? [lat, dist] : arm === 'east' ? [dist, lat] : [-dist, lat])

/** Rectangle from arm distance d0..d1 and lateral l0..l1. */
function armRect(arm, d0, d1, l0, l1, y, color) {
  const [ax, az] = armPt(arm, d0, l0), [bx, bz] = armPt(arm, d1, l1)
  return rect(Math.min(ax, bx), Math.min(az, bz), Math.max(ax, bx), Math.max(az, bz), y, color)
}

// turn arrows in local lane coordinates: x to the driver's right, y forward (metres)
const ARROWS = {
  straight: [[[-0.15, 0], [0.15, 0], [0.15, 2.4], [-0.15, 2.4]], [[-0.6, 2.4], [0.6, 2.4], [0, 3.6]]],
  right: [[[-0.15, 0], [0.15, 0], [0.15, 1.6], [-0.15, 1.6]], [[-0.15, 1.3], [1.5, 1.3], [1.5, 1.6], [-0.15, 1.6]], [[1.5, 0.85], [1.5, 2.05], [2.6, 1.45]]],
  left: [[[-0.15, 0], [0.15, 0], [0.15, 1.6], [-0.15, 1.6]], [[0.15, 1.3], [-1.5, 1.3], [-1.5, 1.6], [0.15, 1.6]], [[-1.5, 0.85], [-1.5, 2.05], [-2.6, 1.45]]],
  uturn: [[[0.5, 0], [0.8, 0], [0.8, 2.0], [0.5, 2.0]], [[-0.5, 1.7], [0.8, 1.7], [0.8, 2.0], [-0.5, 2.0]],
          [[-0.5, 0.6], [-0.2, 0.6], [-0.2, 2.0], [-0.5, 2.0]], [[-0.85, 0.7], [0.15, 0.7], [-0.35, -0.3]]],
}

function roadPolys(layout) {
  const B = boxHalf(layout)
  const sd = stopDist(layout)
  const round = layout.junction === 'roundabout'
  const P = []
  if (round) {
    P.push(disc(B + 3, 0.05, KERB), disc(B, 0.08, ASPHALT))
  } else {
    P.push(rect(-B - 4, -B - 4, B + 4, B + 4, 0.03, KERB), rect(-B, -B, B, B, 0.08, ASPHALT))
  }
  for (const arm of ARMS) {
    const a = layout.arms[arm]
    if (!a.enabled) continue
    const L = a.length_m
    const [lo, hi] = lateralSpan(layout, arm)
    const [rx, rz] = rightVec(arm)
    const rs = arm === 'north' || arm === 'south' ? rx : rz            // side of the inbound lanes
    const din = lanesIn(a), dout = lanesOut(a)
    const start = round ? B - 1.5 : B
    P.push(armRect(arm, start, L, lo - 4, lo, 0.05, KERB), armRect(arm, start, L, hi, hi + 4, 0.05, KERB))
    P.push(armRect(arm, start, L, lo, hi, 0.08, ASPHALT))
    if (a.lane_type === 'bus') P.push(armRect(arm, B, L, 0, rs * LANE_W * din, 0.1, '#8b5a2b'))
    // centre line + dashed lane dividers
    P.push(armRect(arm, B, L, -0.28, -0.08, 0.13, YELLOW), armRect(arm, B, L, 0.08, 0.28, 0.13, YELLOW))
    const dividers = [...Array.from({ length: din - 1 }, (_, i) => rs * LANE_W * (i + 1)), ...Array.from({ length: dout - 1 }, (_, j) => -rs * LANE_W * (j + 1))]
    for (const lat of dividers) for (let d = B + 4; d + 3 < L - 3; d += 6) P.push(armRect(arm, d, d + 3, lat - 0.1, lat + 0.1, 0.13, WHITE))
    if (a.lane_type === 'tram') {
      for (let k = 0; k < din + dout; k++) {
        const c = k < din ? rs * LANE_W * (k + 0.5) : -rs * LANE_W * (k - din + 0.5)
        P.push(armRect(arm, B, L, c - 1.0, c - 0.88, 0.15, KERB), armRect(arm, B, L, c + 0.88, c + 1.0, 0.15, KERB))
        for (let d = B + 1; d < L; d += 2) P.push(armRect(arm, d, d + 0.3, c - 1.4, c + 1.4, 0.11, '#57534e'))
      }
    }
    if (round) {
      for (let i = 0; i < din; i++) P.push(armRect(arm, B - 0.6, B - 0.2, rs * LANE_W * i, rs * LANE_W * (i + 1), 0.14, WHITE))   // yield line
    } else {
      P.push(armRect(arm, sd - 0.2, sd + 0.2, 0, rs * LANE_W * din, 0.14, WHITE))                                     // stop line
      for (let i = 0; i < din; i++) {                                                                                     // lane arrows
        const moves = laneMoves(layout, arm, i)
        const centre = rs * LANE_W * (i + 0.5)
        moves.forEach((m, k) => {
          const dist = sd + 6 + k * 5
          const [ox, oz] = OUT[arm]
          const fwd = [-ox, -oz]                                                                       // direction of travel
          const right = [-fwd[1], fwd[0]]
          const base = armPt(arm, dist, centre)
          for (const poly of ARROWS[m]) {
            P.push({ pts: poly.map(([lx, ly]) => [base[0] + right[0] * lx + fwd[0] * ly, base[1] + right[1] * lx + fwd[1] * ly]), y: 0.14, color: '#e5e7eb' })
          }
        })
      }
    }
    if (hasCrossing(layout, arm)) {
      const [clo, chi] = crossingSpan(layout, arm)
      const c = B + 2.5
      for (let lat = clo + 0.6; lat < chi - 0.3; lat += 1.2) P.push(armRect(arm, c - 1.5, c + 1.5, lat, lat + 0.6, 0.14, '#e5e7eb'))
    }
  }
  if (round) {
    const d = roundaboutDims(layout)
    P.push(disc(d.island + 0.7, 0.16, '#c8c8cd'), disc(d.island, 0.2, '#5a8f50'))
    P.push(disc(d.outer - 0.2, 0.12, '#666666', 64))
  }
  return P
}

function useMerged(polys) {
  return useMemo(() => {
    const pos = [], col = []
    const c = new Color()
    for (const { pts, y, color } of polys) {
      c.set(color)
      for (let i = 1; i < pts.length - 1; i++) {
        for (const p of [pts[0], pts[i], pts[i + 1]]) { pos.push(p[0], y, p[1]); col.push(c.r, c.g, c.b) }
      }
    }
    const g = new BufferGeometry()
    g.setAttribute('position', new Float32BufferAttribute(pos, 3))
    g.setAttribute('color', new Float32BufferAttribute(col, 3))
    g.computeVertexNormals()
    return g
  }, [polys])
}

/** Short road stub + barrier beyond the box where a straight route has no road to lead to. */
function DeadEnd({ layout, arm }) {
  const B = boxHalf(layout)
  const src = OPPOSITE[arm]                                        // the arm whose vehicles drive into this dead end
  const a = layout.arms[src]
  const [lo, hi] = lateralSpan(layout, src)                        // same axis, same lateral interval
  const [rx, rz] = rightVec(src)
  const rs = src === 'north' || src === 'south' ? rx : rz
  const din = lanesIn(a)
  const blocks = []
  for (let k = 0; k < din * 2; k++) {
    const lat = rs * (k + 0.5) * (LANE_W / 2)
    const [x, z] = armPt(arm, B + 6.3, lat)
    blocks.push(<mesh key={k} position={[x, 0.7, z]} castShadow>
      <boxGeometry args={arm === 'north' || arm === 'south' ? [2, 1.2, 0.4] : [0.4, 1.2, 2]} /><meshLambertMaterial color={k % 2 ? '#f8fafc' : '#dc2626'} />
    </mesh>)
  }
  const polys = useMemo(() => [armRect(arm, B, B + 6, lo - 4, lo, 0.05, KERB), armRect(arm, B, B + 6, hi, hi + 4, 0.05, KERB),
                               armRect(arm, B, B + 6, lo, hi, 0.08, ASPHALT)], [arm, B, lo, hi])
  const geo = useMerged(polys)
  return <group><mesh geometry={geo} receiveShadow><meshLambertMaterial vertexColors side={DoubleSide} /></mesh>{blocks}</group>
}

export default function RoadSystem({ layout }) {
  const polys = useMemo(() => roadPolys(layout), [layout])
  const geo = useMerged(polys)
  const arms = layout.arms
  const dead = layout.junction === 'roundabout' ? [] : ARMS.filter(a => !arms[a].enabled && arms[OPPOSITE[a]].enabled &&
    Array.from({ length: lanesIn(arms[OPPOSITE[a]]) }, (_, i) => laneMoves(layout, OPPOSITE[a], i)).flat().includes('straight'))
  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.05, 0]} receiveShadow>
        <planeGeometry args={[500, 500]} /><meshLambertMaterial color="#4a7c4a" />
      </mesh>
      <mesh geometry={geo} receiveShadow><meshLambertMaterial vertexColors side={DoubleSide} /></mesh>
      {dead.map(a => <DeadEnd key={a} layout={layout} arm={a} />)}
    </group>
  )
}
