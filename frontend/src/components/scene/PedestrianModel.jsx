/**
 * PedestrianModel — thin cylinder body + head, walking across a crosswalk.
 * position_m runs 0..12 across the crosswalk (negative = still on the sidewalk); `direction` (+1/-1) says
 * which side the pedestrian starts from and `offset` is the lateral lane inside the crosswalk band.
 */
import { useRef, useLayoutEffect, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import { Vector3 } from 'three'

const CROSSING_CENTER = 18.5
const CROSSING_WIDTH = 12

export function pedestrianWorldPosition(crossing_id, position_m, direction = 1, offset = 0) {
  const along = direction * (position_m - CROSSING_WIDTH / 2)
  switch (crossing_id) {
    case 'PC-N': return [along, 0, -CROSSING_CENTER + offset]
    case 'PC-S': return [along, 0, CROSSING_CENTER + offset]
    case 'PC-E': return [CROSSING_CENTER + offset, 0, along]
    case 'PC-W': return [-CROSSING_CENTER + offset, 0, along]
    default: return [0, 0, 0]
  }
}

const COLORS = { crossing: '#fbbf24', waiting_for_green: '#f87171', walking_to_crossing: '#60a5fa' }

export default function PedestrianModel({ crossing_id, state, position_m, direction, offset }) {
  const ref = useRef()
  const target = useMemo(() => new Vector3(), [])
  target.set(...pedestrianWorldPosition(crossing_id, position_m, direction, offset))
  const color = COLORS[state] || '#60a5fa'

  useLayoutEffect(() => { ref.current.position.copy(target) }, [])  // eslint-disable-line react-hooks/exhaustive-deps
  useFrame((_, dt) => { ref.current?.position.lerp(target, 1 - Math.exp(-dt * 14)) })

  return (
    <group ref={ref}>
      <mesh position={[0, 0.8, 0]} castShadow>
        <cylinderGeometry args={[0.18, 0.18, 1.3, 8]} />
        <meshLambertMaterial color={color} />
      </mesh>
      <mesh position={[0, 1.6, 0]} castShadow>
        <sphereGeometry args={[0.2, 8, 8]} />
        <meshLambertMaterial color="#f1c9a5" />
      </mesh>
    </group>
  )
}
