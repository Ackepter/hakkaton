/**
 * SceneEnvironment — sky, buildings, trees.
 */

export default function SceneEnvironment() {
  return (
    <group>
      <Sky />
      <Buildings />
      <Trees />
    </group>
  )
}

function Sky() {
  return (
    <mesh>
      <sphereGeometry args={[500, 16, 16]} />
      <meshBasicMaterial color="#87ceeb" side={2} />
    </mesh>
  )
}

const BUILDING_POSITIONS = [
  [-60, 0, -60], [60, 0, -60], [-60, 0, 60], [60, 0, 60],
  [-90, 0, -30], [90, 0, -30], [-90, 0, 30], [90, 0, 30],
  [-30, 0, -90], [30, 0, -90], [-30, 0, 90], [30, 0, 90],
]

function Buildings() {
  return (
    <group>
      {BUILDING_POSITIONS.map(([x, y, z], i) => {
        const h = 8 + (i % 4) * 5
        const w = 8 + (i % 3) * 3
        return (
          <mesh key={i} position={[x, h / 2, z]} castShadow receiveShadow>
            <boxGeometry args={[w, h, w]} />
            <meshLambertMaterial color={`hsl(${200 + i * 15}, 30%, 55%)`} />
          </mesh>
        )
      })}
    </group>
  )
}

const TREE_POSITIONS = [
  [-22, 0, -22], [22, 0, -22], [-22, 0, 22], [22, 0, 22],
  [-22, 0, -5], [-22, 0, 5], [22, 0, -5], [22, 0, 5],
  [-5, 0, -22], [5, 0, -22], [-5, 0, 22], [5, 0, 22],
]

function Trees() {
  return (
    <group>
      {TREE_POSITIONS.map(([x, y, z], i) => (
        <group key={i} position={[x, 0, z]}>
          {/* Trunk */}
          <mesh position={[0, 1.2, 0]}>
            <cylinderGeometry args={[0.2, 0.3, 2.4, 6]} />
            <meshLambertMaterial color="#8B4513" />
          </mesh>
          {/* Canopy */}
          <mesh position={[0, 3.5, 0]}>
            <sphereGeometry args={[1.8, 8, 6]} />
            <meshLambertMaterial color={`hsl(${120 + (i % 4) * 10}, 50%, ${35 + (i % 3) * 5}%)`} />
          </mesh>
        </group>
      ))}
    </group>
  )
}
