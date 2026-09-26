/**
 * VehicleModel — renders a vehicle as a colored box.
 * Position is computed from lane_id + position_m using the same formula as world.py.
 */
import { useRef } from 'react'
import { useFrame } from '@react-three/fiber'

const ARM_LENGTH = 80
const LANE_WIDTH = 4
const INTERSECTION_HALF = 16

const VEHICLE_COLORS = {
  car: '#3b82f6',
  truck: '#f97316',
  bus: '#22c55e',
  tram: '#a855f7',
  emergency: '#ef4444',
  taxi: '#eab308',
  motorcycle: '#06b6d4',
  bicycle: '#84cc16',
}

const VEHICLE_DIMS = {
  car:       [4.5, 1.5, 2.0],
  truck:     [10.0, 2.5, 2.5],
  bus:       [10.0, 2.8, 2.5],
  tram:      [18.0, 3.0, 2.8],
  emergency: [5.5, 1.8, 2.2],
  taxi:      [4.5, 1.5, 2.0],
  motorcycle:[2.2, 1.2, 0.8],
  bicycle:   [1.8, 1.0, 0.6],
}

function getVehicle3DPosition(lane_id, position_m) {
  const parts = lane_id.split('-')
  const direction = parts[0]
  const isIn = parts[1] === 'in'

  if (direction === 'north') {
    const z = isIn ? -(ARM_LENGTH - position_m) : -(position_m + INTERSECTION_HALF)
    const x = isIn ? -LANE_WIDTH / 2 : LANE_WIDTH / 2
    return [x, 0.75, z]
  } else if (direction === 'south') {
    const z = isIn ? (ARM_LENGTH - position_m) : (position_m + INTERSECTION_HALF)
    const x = isIn ? LANE_WIDTH / 2 : -LANE_WIDTH / 2
    return [x, 0.75, z]
  } else if (direction === 'east') {
    const x = isIn ? (ARM_LENGTH - position_m) : (position_m + INTERSECTION_HALF)
    const z = isIn ? -LANE_WIDTH / 2 : LANE_WIDTH / 2
    return [x, 0.75, z]
  } else if (direction === 'west') {
    const x = isIn ? -(ARM_LENGTH - position_m) : -(position_m + INTERSECTION_HALF)
    const z = isIn ? LANE_WIDTH / 2 : -LANE_WIDTH / 2
    return [x, 0.75, z]
  }
  return [0, 0.75, 0]
}

function getVehicleRotation(lane_id) {
  const dir = lane_id.split('-')[0]
  switch (dir) {
    case 'north': case 'south': return [0, 0, 0]
    case 'east':  case 'west':  return [0, Math.PI / 2, 0]
    default: return [0, 0, 0]
  }
}

export default function VehicleModel({ id, vehicle_type, lane_id, position_m, state }) {
  const meshRef = useRef()
  const pos = getVehicle3DPosition(lane_id, position_m)
  const rot = getVehicleRotation(lane_id)
  const color = VEHICLE_COLORS[vehicle_type] || '#888888'
  const dims = VEHICLE_DIMS[vehicle_type] || [4.5, 1.5, 2.0]

  // Emergency vehicles pulse (emissive effect)
  const isEmergency = vehicle_type === 'emergency'

  useFrame(({ clock }) => {
    if (meshRef.current && isEmergency) {
      const t = clock.elapsedTime
      meshRef.current.material.emissiveIntensity = 0.3 + 0.3 * Math.sin(t * 8)
    }
  })

  return (
    <mesh ref={meshRef} position={pos} rotation={rot} castShadow>
      <boxGeometry args={dims} />
      <meshLambertMaterial
        color={color}
        emissive={isEmergency ? '#ff0000' : '#000000'}
        emissiveIntensity={0}
        opacity={state === 'waiting' ? 0.9 : 1.0}
        transparent
      />
    </mesh>
  )
}
