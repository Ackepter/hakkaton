/**
 * TrafficLightModel — pole + housing + 3 bulbs.
 *
 * The bulbs sit on the local +Z face. Each head must face the drivers APPROACHING it and stand on the driver's
 * right-hand side just past the stop line (`pos` = builder/geometry.lightPole, it grows with the number of lanes):
 *   north arm: traffic comes from -Z heading +Z -> head faces -Z (rotY = PI)
 *   south arm: head faces +Z (rotY = 0)     east arm: head faces +X (PI/2)     west arm: head faces -X (-PI/2)
 */
const LIGHT_ROTATIONS = {
  north: [0, Math.PI, 0],
  south: [0, 0, 0],
  east: [0, Math.PI / 2, 0],
  west: [0, -Math.PI / 2, 0],
}

const OFF = '#2a2a2a'
const BULB = {
  RED: { red: '#ff2a2a', yellow: OFF, green: OFF },
  YELLOW: { red: OFF, yellow: '#ffdd00', green: OFF },
  GREEN: { red: OFF, yellow: OFF, green: '#22ff55' },
}

function Bulb({ y, color }) {
  const lit = color !== OFF
  return (
    <mesh position={[0, y, 0.19]}>
      <sphereGeometry args={[0.2, 12, 12]} />
      <meshStandardMaterial color={color} emissive={lit ? color : '#000000'} emissiveIntensity={lit ? 1.6 : 0} />
    </mesh>
  )
}

export default function TrafficLightModel({ direction, state, pos: xz = [0, 0] }) {
  const pos = [xz[0], 0, xz[1]]
  const rot = LIGHT_ROTATIONS[direction] || [0, 0, 0]
  const c = BULB[state] || BULB.RED

  return (
    <group position={pos} rotation={rot}>
      <mesh position={[0, 2.5, 0]} castShadow>
        <cylinderGeometry args={[0.12, 0.12, 5, 8]} />
        <meshLambertMaterial color="#555555" />
      </mesh>
      <mesh position={[0, 5.8, 0]} castShadow>
        <boxGeometry args={[0.6, 1.8, 0.35]} />
        <meshLambertMaterial color="#1c1c1c" />
      </mesh>
      <Bulb y={6.4} color={c.red} />
      <Bulb y={5.8} color={c.yellow} />
      <Bulb y={5.2} color={c.green} />
    </group>
  )
}
