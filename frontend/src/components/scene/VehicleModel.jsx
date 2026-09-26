/**
 * VehicleModel — coloured box, smoothly interpolated between simulation updates.
 *
 * Path geometry matches the engine (smart_intersection/engine/world.py): position_m is the centre of the
 * vehicle along an inbound path that runs straight through the box to the far arm, so
 * signed distance from the centre = position_m - 80.
 * BoxGeometry length is along local X: N/S traffic (moving along Z) is rotated 90 deg, E/W is not.
 */
import { useRef, useLayoutEffect, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import { Vector3 } from 'three'

const ARM_LENGTH = 80
const LANE_OFFSET = 2

const COLORS = {
  car: '#3b82f6', truck: '#f97316', bus: '#22c55e', tram: '#a855f7',
  emergency: '#ef4444', taxi: '#eab308', motorcycle: '#06b6d4', bicycle: '#84cc16',
}

// [length, height, width]
const DIMS = {
  car: [4.5, 1.5, 2.0], truck: [12, 2.8, 2.5], bus: [12, 3.0, 2.5], tram: [20, 3.2, 2.6],
  emergency: [5.5, 1.9, 2.2], taxi: [4.5, 1.5, 2.0], motorcycle: [2.2, 1.2, 0.8], bicycle: [1.8, 1.0, 0.6],
}

export function vehicleWorldPosition(direction, position_m, height) {
  const t = position_m - ARM_LENGTH
  switch (direction) {
    case 'north': return [-LANE_OFFSET, height / 2, t]
    case 'south': return [LANE_OFFSET, height / 2, -t]
    case 'east': return [-t, height / 2, -LANE_OFFSET]
    case 'west': return [t, height / 2, LANE_OFFSET]
    default: return [0, height / 2, 0]
  }
}

const ROTATION = {
  north: [0, Math.PI / 2, 0], south: [0, Math.PI / 2, 0], east: [0, 0, 0], west: [0, 0, 0],
}

export default function VehicleModel({ vehicle_type, direction, position_m, state }) {
  const ref = useRef()
  const dims = DIMS[vehicle_type] || DIMS.car
  const target = useMemo(() => new Vector3(), [])
  target.set(...vehicleWorldPosition(direction, position_m, dims[1]))
  const emergency = vehicle_type === 'emergency'

  useLayoutEffect(() => { ref.current.position.copy(target) }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  useFrame(({ clock }, dt) => {
    const m = ref.current
    if (!m) return
    m.position.lerp(target, 1 - Math.exp(-dt * 16))
    if (emergency) m.material.emissiveIntensity = 0.35 + 0.35 * Math.sin(clock.elapsedTime * 10)
  })

  return (
    <mesh ref={ref} rotation={ROTATION[direction] || [0, 0, 0]} castShadow>
      <boxGeometry args={dims} />
      <meshLambertMaterial
        color={COLORS[vehicle_type] || '#888888'}
        emissive={emergency ? '#ff0000' : '#000000'}
        emissiveIntensity={0}
      />
    </mesh>
  )
}
