/**
 * TrafficLightModel — pole + housing + 3 bulbs.
 */

const LIGHT_POSITIONS = {
  north: [-6, 0, -19],
  south: [ 6, 0,  19],
  east:  [ 19, 0,  6],
  west:  [-19, 0, -6],
}

const BULB_COLORS = {
  RED:    { red: '#ff2222', yellow: '#333', green: '#333' },
  YELLOW: { red: '#333', yellow: '#ffee00', green: '#333' },
  GREEN:  { red: '#333', yellow: '#333', green: '#22ff44' },
}

export default function TrafficLightModel({ id, direction, state }) {
  const basePos = LIGHT_POSITIONS[direction] || [0, 0, 0]
  const colors = BULB_COLORS[state] || BULB_COLORS.RED

  return (
    <group position={basePos}>
      {/* Pole */}
      <mesh position={[0, 2.5, 0]} castShadow>
        <cylinderGeometry args={[0.12, 0.12, 5, 8]} />
        <meshLambertMaterial color="#555555" />
      </mesh>

      {/* Housing */}
      <mesh position={[0, 5.8, 0]} castShadow>
        <boxGeometry args={[0.6, 1.8, 0.35]} />
        <meshLambertMaterial color="#222222" />
      </mesh>

      {/* Red bulb */}
      <mesh position={[0, 6.4, 0.18]}>
        <sphereGeometry args={[0.2, 8, 8]} />
        <meshStandardMaterial
          color={colors.red}
          emissive={colors.red !== '#333' ? colors.red : '#000'}
          emissiveIntensity={colors.red !== '#333' ? 1.5 : 0}
        />
      </mesh>

      {/* Yellow bulb */}
      <mesh position={[0, 5.8, 0.18]}>
        <sphereGeometry args={[0.2, 8, 8]} />
        <meshStandardMaterial
          color={colors.yellow}
          emissive={colors.yellow !== '#333' ? colors.yellow : '#000'}
          emissiveIntensity={colors.yellow !== '#333' ? 1.5 : 0}
        />
      </mesh>

      {/* Green bulb */}
      <mesh position={[0, 5.2, 0.18]}>
        <sphereGeometry args={[0.2, 8, 8]} />
        <meshStandardMaterial
          color={colors.green}
          emissive={colors.green !== '#333' ? colors.green : '#000'}
          emissiveIntensity={colors.green !== '#333' ? 1.5 : 0}
        />
      </mesh>
    </group>
  )
}
