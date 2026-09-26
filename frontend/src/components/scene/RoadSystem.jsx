/**
 * RoadSystem — the streets of a layout: asphalt, sidewalks, markings, stop lines, crosswalks, bus lanes, tram rails,
 * and barriers where a straight route ends without a road.
 *
 * Every arm is drawn in its own local frame: +z runs outward from the intersection, x across, and the inbound lane
 * is always x in [0, 4] (right-hand traffic). Rotating the frame gives north / south / east / west.
 */
import { ARMS, OPPOSITE } from '../../builder/geometry'

const HALF = 16          // half of the intersection box
const STOP = 21          // stop line distance from the centre (matches the simulation)
const CROSS = 18.5       // crosswalk centre distance
const FLAT = [-Math.PI / 2, 0, 0]
const ROT = { north: Math.PI, south: 0, east: Math.PI / 2, west: -Math.PI / 2 }
const STUB = HALF + 6    // dead-end stub length (simulation: vehicles vanish 6 m after the box)

const Quad = ({ pos, size, color, y = 0.1, opacity = 1 }) => (
  <mesh rotation={FLAT} position={[pos[0], y, pos[1]]} receiveShadow>
    <planeGeometry args={size} />
    <meshLambertMaterial color={color} transparent={opacity < 1} opacity={opacity} />
  </mesh>
)

function Arm({ arm, cfg }) {
  const L = cfg.length_m
  const len = L - HALF
  const mid = HALF + len / 2
  const dashes = []
  for (let z = HALF + 4; z < L - 3; z += 6) dashes.push(z)
  return (
    <group rotation={[0, ROT[arm], 0]}>
      <Quad pos={[-6, mid]} size={[4, len]} color="#9ca3af" y={0.05} />
      <Quad pos={[6, mid]} size={[4, len]} color="#9ca3af" y={0.05} />
      <Quad pos={[0, mid]} size={[8, len]} color="#555555" y={0.08} />
      {cfg.lane_type === 'bus' && <Quad pos={[2, mid]} size={[4, len]} color="#b45309" y={0.10} opacity={0.75} />}
      {dashes.map(z => <Quad key={z} pos={[0, z + 1.5]} size={[0.2, 3]} color="#ffffff" y={0.13} />)}
      {cfg.lane_type === 'tram' && [1.3, 2.7, -1.3, -2.7].map(x => (
        <mesh key={x} position={[x, 0.15, mid]}><boxGeometry args={[0.12, 0.08, len]} /><meshLambertMaterial color="#9ca3af" /></mesh>
      ))}
      {cfg.lane_type === 'tram' && Array.from({ length: Math.floor(len / 2) }, (_, i) => HALF + 1 + i * 2).map(z => (
        <mesh key={z} position={[0, 0.11, z]}><boxGeometry args={[6, 0.05, 0.3]} /><meshLambertMaterial color="#57534e" /></mesh>
      ))}
      <Quad pos={[2, STOP]} size={[4, 0.4]} color="#ffffff" y={0.14} />
      {cfg.crossing && Array.from({ length: 10 }, (_, i) => -5.4 + i * 1.2).map(x => (
        <Quad key={x} pos={[x, CROSS]} size={[0.6, 3]} color="#e5e7eb" y={0.14} />
      ))}
    </group>
  )
}

/** Short road stub + barrier on the far side of the box when the opposite arm is missing. */
function DeadEnd({ arm }) {
  return (
    <group rotation={[0, ROT[arm], 0]}>
      <Quad pos={[0, (HALF + STUB) / 2]} size={[8, STUB - HALF]} color="#555555" y={0.08} />
      <Quad pos={[-6, (HALF + STUB) / 2]} size={[4, STUB - HALF]} color="#9ca3af" y={0.05} />
      <Quad pos={[6, (HALF + STUB) / 2]} size={[4, STUB - HALF]} color="#9ca3af" y={0.05} />
      {[-3, -1, 1, 3].map((x, i) => (
        <mesh key={x} position={[x, 0.7, STUB + 0.3]} castShadow>
          <boxGeometry args={[2, 1.2, 0.4]} /><meshLambertMaterial color={i % 2 ? '#f8fafc' : '#dc2626'} />
        </mesh>
      ))}
    </group>
  )
}

export default function RoadSystem({ layout }) {
  const arms = layout.arms
  return (
    <group>
      <mesh rotation={FLAT} position={[0, -0.05, 0]} receiveShadow>
        <planeGeometry args={[400, 400]} /><meshLambertMaterial color="#4a7c4a" />
      </mesh>
      <Quad pos={[0, 0]} size={[HALF * 2 + 8, HALF * 2 + 8]} color="#9ca3af" y={0.03} />
      <Quad pos={[0, 0]} size={[HALF * 2, HALF * 2]} color="#555555" y={0.08} />
      {ARMS.filter(a => arms[a].enabled).map(a => <Arm key={a} arm={a} cfg={arms[a]} />)}
      {ARMS.filter(a => !arms[a].enabled && arms[OPPOSITE[a]].enabled).map(a => <DeadEnd key={a} arm={a} />)}
    </group>
  )
}
