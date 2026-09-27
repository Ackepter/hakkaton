/**
 * VehicleModel — coloured box, smoothly interpolated between simulation updates.
 *
 * The simulation publishes the world position (x, z) and heading of every vehicle centre (heading = atan2(dz, dx) in the
 * ground plane), so turns, u-turns and roundabouts need no geometry here. BoxGeometry length runs along local X:
 * rotation.y = -heading points it along the direction of travel.
 */
import { useRef, useLayoutEffect, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import { Vector3 } from 'three'

const COLORS = {
  car: '#3b82f6', truck: '#f97316', bus: '#22c55e', tram: '#a855f7',
  emergency: '#ef4444', taxi: '#eab308', motorcycle: '#06b6d4', bicycle: '#84cc16',
}

// [length, height, width]
const DIMS = {
  car: [4.5, 1.5, 2.0], truck: [12, 2.8, 2.5], bus: [12, 3.0, 2.5], tram: [20, 3.2, 2.6],
  emergency: [5.5, 1.9, 2.2], taxi: [4.5, 1.5, 2.0], motorcycle: [2.2, 1.2, 0.8], bicycle: [1.8, 1.0, 0.6],
}

const shortest = (from, to) => from + ((((to - from + Math.PI) % (2 * Math.PI)) + 2 * Math.PI) % (2 * Math.PI) - Math.PI)

export default function VehicleModel({ vehicle_type, x = 0, z = 0, heading = 0, state }) {
  const ref = useRef()
  const dims = DIMS[vehicle_type] || DIMS.car
  const target = useMemo(() => new Vector3(), [])
  target.set(x, dims[1] / 2, z)
  const emergency = vehicle_type === 'emergency'

  useLayoutEffect(() => { ref.current.position.copy(target); ref.current.rotation.y = -heading }, [])  // eslint-disable-line react-hooks/exhaustive-deps

  useFrame(({ clock }, dt) => {
    const m = ref.current
    if (!m) return
    const k = 1 - Math.exp(-dt * 16)
    m.position.lerp(target, k)
    m.rotation.y += (shortest(m.rotation.y, -heading) - m.rotation.y) * k
    if (emergency) m.material.emissiveIntensity = 0.35 + 0.35 * Math.sin(clock.elapsedTime * 10)
  })

  return (
    <mesh ref={ref} castShadow>
      <boxGeometry args={dims} />
      <meshLambertMaterial
        color={COLORS[vehicle_type] || '#888888'}
        emissive={emergency ? '#ff0000' : '#000000'}
        emissiveIntensity={0}
      />
    </mesh>
  )
}
