/**
 * PedestrianModel — thin cylinder body + head, walking across a crosswalk. The simulation publishes the world
 * position (x, z) of every pedestrian.
 */
import { useRef, useLayoutEffect, useMemo } from 'react'
import { useFrame } from '@react-three/fiber'
import { Vector3 } from 'three'

const COLORS = { crossing: '#fbbf24', waiting_for_green: '#f87171', walking_to_crossing: '#60a5fa' }

export default function PedestrianModel({ state, x = 0, z = 0 }) {
  const ref = useRef()
  const target = useMemo(() => new Vector3(), [])
  target.set(x, 0, z)
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
