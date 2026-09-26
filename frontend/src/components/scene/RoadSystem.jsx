/**
 * RoadSystem — asphalt, lane markings, sidewalks.
 * All geometry built from Three.js primitives (no external files).
 */
const ARM_LENGTH = 80
const LANE_WIDTH = 4
const HALF = 16  // intersection half-width (4 lanes × 4m)
const ROAD_WIDTH = LANE_WIDTH * 2  // 2 lanes per arm (in + out)

export default function RoadSystem() {
  return (
    <group>
      {/* Ground plane */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.01, 0]} receiveShadow>
        <planeGeometry args={[300, 300]} />
        <meshLambertMaterial color="#4a7c4a" />
      </mesh>

      {/* Intersection box */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]} receiveShadow>
        <planeGeometry args={[HALF * 2, HALF * 2]} />
        <meshLambertMaterial color="#444444" />
      </mesh>

      {/* North arm */}
      <RoadArm direction="north" />
      {/* South arm */}
      <RoadArm direction="south" />
      {/* East arm */}
      <RoadArm direction="east" />
      {/* West arm */}
      <RoadArm direction="west" />

      {/* Lane markings */}
      <LaneMarkings />
    </group>
  )
}

function RoadArm({ direction }) {
  const armLen = ARM_LENGTH - HALF
  const halfArm = armLen / 2 + HALF / 2

  let position, rotation
  switch (direction) {
    case 'north': position = [0, 0, -(HALF + armLen / 2)]; rotation = [-Math.PI / 2, 0, 0]; break
    case 'south': position = [0, 0,  (HALF + armLen / 2)]; rotation = [-Math.PI / 2, 0, 0]; break
    case 'east':  position = [ (HALF + armLen / 2), 0, 0]; rotation = [-Math.PI / 2, Math.PI / 2, 0]; break
    case 'west':  position = [-(HALF + armLen / 2), 0, 0]; rotation = [-Math.PI / 2, Math.PI / 2, 0]; break
    default: return null
  }

  return (
    <mesh rotation={rotation} position={position} receiveShadow>
      <planeGeometry args={[ROAD_WIDTH, armLen]} />
      <meshLambertMaterial color="#444444" />
    </mesh>
  )
}

function LaneMarkings() {
  const lines = []
  const armLen = ARM_LENGTH - HALF

  // Dashed center lines on N/S arm
  for (let z = HALF; z < HALF + armLen; z += 6) {
    lines.push(
      <mesh key={`ns-${z}`} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.01, -(z + 1.5)]}>
        <planeGeometry args={[0.2, 3]} />
        <meshLambertMaterial color="#ffffff" />
      </mesh>
    )
    lines.push(
      <mesh key={`ss-${z}`} rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.01, z + 1.5]}>
        <planeGeometry args={[0.2, 3]} />
        <meshLambertMaterial color="#ffffff" />
      </mesh>
    )
  }
  // Dashed center lines on E/W arm
  for (let x = HALF; x < HALF + armLen; x += 6) {
    lines.push(
      <mesh key={`ew-${x}`} rotation={[-Math.PI / 2, 0, 0]} position={[x + 1.5, 0.01, 0]}>
        <planeGeometry args={[3, 0.2]} />
        <meshLambertMaterial color="#ffffff" />
      </mesh>
    )
    lines.push(
      <mesh key={`ww-${x}`} rotation={[-Math.PI / 2, 0, 0]} position={[-(x + 1.5), 0.01, 0]}>
        <planeGeometry args={[3, 0.2]} />
        <meshLambertMaterial color="#ffffff" />
      </mesh>
    )
  }

  // Zebra crossings
  ;['north', 'south', 'east', 'west'].forEach((dir, i) => {
    const crossStripes = 4
    for (let s = 0; s < crossStripes; s++) {
      const offset = -ROAD_WIDTH / 2 + (s + 0.5) * (ROAD_WIDTH / crossStripes)
      let pos
      switch (dir) {
        case 'north': pos = [offset, 0.01, -(HALF + 1.5)]; break
        case 'south': pos = [offset, 0.01,  HALF + 1.5]; break
        case 'east':  pos = [ HALF + 1.5, 0.01, offset]; break
        case 'west':  pos = [-(HALF + 1.5), 0.01, offset]; break
      }
      lines.push(
        <mesh key={`cross-${dir}-${s}`} rotation={[-Math.PI / 2, dir === 'east' || dir === 'west' ? Math.PI / 2 : 0, 0]} position={pos}>
          <planeGeometry args={[LANE_WIDTH * 0.4, 3]} />
          <meshLambertMaterial color="#cccccc" opacity={0.8} transparent />
        </mesh>
      )
    }
  })

  return <group>{lines}</group>
}
