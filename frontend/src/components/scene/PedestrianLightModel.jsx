/**
 * PedestrianLightModel — a short pole with a red/green walking-figure signal, one per crosswalk.
 * A first-class controllable light (see SimulationEngine.set_ped_light_state): its own state, own switch count,
 * shown here as a simple two-colour head rather than the 3-bulb vehicle head.
 */
import { Html } from '@react-three/drei'

export default function PedestrianLightModel({ direction, state, pos: xz = [0, 0] }) {
  const walk = state === 'GREEN'
  const color = walk ? '#22ff55' : '#ff2a2a'
  return (
    <group position={[xz[0], 0, xz[1]]}>
      <mesh position={[0, 1.1, 0]} castShadow>
        <cylinderGeometry args={[0.06, 0.06, 2.2, 8]} />
        <meshLambertMaterial color="#555555" />
      </mesh>
      <mesh position={[0, 2.15, 0]} castShadow>
        <boxGeometry args={[0.35, 0.55, 0.22]} />
        <meshLambertMaterial color="#1c1c1c" />
      </mesh>
      <mesh position={[0, 2.15, 0.12]}>
        <circleGeometry args={[0.22, 16]} />
        <meshStandardMaterial color={color} emissive={color} emissiveIntensity={1.5} />
      </mesh>
      <Html position={[0, 2.6, 0]} center distanceFactor={90} style={{ pointerEvents: 'none' }}>
        <div style={{ fontSize: 13 }}>{walk ? '🚶' : '✋'}</div>
      </Html>
    </group>
  )
}
