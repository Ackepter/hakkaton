/**
 * PedestrianModel — cylinder body + sphere head.
 */

const INTERSECTION_HALF = 16
const CROSSING_WIDTH = 12

const CROSSING_POSITIONS = {
  'PC-N': { base: [0, 0, -(INTERSECTION_HALF + 1)], axis: 'x' },
  'PC-S': { base: [0, 0,  INTERSECTION_HALF + 1],  axis: 'x' },
  'PC-E': { base: [ INTERSECTION_HALF + 1, 0, 0],  axis: 'z' },
  'PC-W': { base: [-(INTERSECTION_HALF + 1), 0, 0], axis: 'z' },
}

function getPedPosition(crossing_id, position_m) {
  const info = CROSSING_POSITIONS[crossing_id]
  if (!info) return [0, 0, 0]
  const [bx, by, bz] = info.base
  const offset = position_m - CROSSING_WIDTH / 2
  if (info.axis === 'x') return [bx + offset, 0, bz]
  return [bx, 0, bz + offset]
}

export default function PedestrianModel({ id, crossing_id, state, position_m }) {
  const pos = getPedPosition(crossing_id, position_m)
  const color = state === 'crossing' ? '#fbbf24' : state === 'waiting_for_green' ? '#f87171' : '#60a5fa'

  return (
    <group position={pos}>
      {/* Body */}
      <mesh position={[0, 0.85, 0]} castShadow>
        <cylinderGeometry args={[0.25, 0.25, 1.4, 8]} />
        <meshLambertMaterial color={color} />
      </mesh>
      {/* Head */}
      <mesh position={[0, 1.8, 0]} castShadow>
        <sphereGeometry args={[0.28, 8, 8]} />
        <meshLambertMaterial color={color} />
      </mesh>
    </group>
  )
}
