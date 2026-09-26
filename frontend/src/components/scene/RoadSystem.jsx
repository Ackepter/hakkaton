/**
 * RoadSystem — asphalt, lane markings, zebra crossings.
 * All geometry built from Three.js primitives (no external files).
 *
 * Coordinate system: X = West→East, Z = North→South, Y = up
 * All planes rotated [-PI/2, 0, 0] to lie flat in XZ plane.
 * E/W arms use swapped geometry args [armLen, ROAD_WIDTH] so length is along X.
 */
const ARM_LENGTH = 80
const LANE_WIDTH = 4
const HALF = 16        // intersection half-width (4 lanes × 4m)
const ROAD_WIDTH = LANE_WIDTH * 2  // 2 lanes per arm

export default function RoadSystem() {
  return (
    <group>
      {/* Green ground */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.02, 0]} receiveShadow>
        <planeGeometry args={[300, 300]} />
        <meshLambertMaterial color="#4a7c4a" />
      </mesh>

      {/* Intersection box */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]} receiveShadow>
        <planeGeometry args={[HALF * 2, HALF * 2]} />
        <meshLambertMaterial color="#555555" />
      </mesh>

      <RoadArm direction="north" />
      <RoadArm direction="south" />
      <RoadArm direction="east" />
      <RoadArm direction="west" />

      <Sidewalks />
      <LaneMarkings />
      <ZebraCrossings />
    </group>
  )
}

function RoadArm({ direction }) {
  const armLen = ARM_LENGTH - HALF  // 64m of road outside intersection

  // All arms laid flat with [-PI/2, 0, 0].
  // N/S: geometry [ROAD_WIDTH, armLen]  → 8m along X, 64m along Z
  // E/W: geometry [armLen, ROAD_WIDTH]  → 64m along X, 8m along Z
  const isNS = direction === 'north' || direction === 'south'
  const geomArgs = isNS ? [ROAD_WIDTH, armLen] : [armLen, ROAD_WIDTH]

  let position
  switch (direction) {
    case 'north': position = [0, 0, -(HALF + armLen / 2)]; break
    case 'south': position = [0, 0,  (HALF + armLen / 2)]; break
    case 'east':  position = [ (HALF + armLen / 2), 0, 0]; break
    case 'west':  position = [-(HALF + armLen / 2), 0, 0]; break
    default: return null
  }

  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={position} receiveShadow>
      <planeGeometry args={geomArgs} />
      <meshLambertMaterial color="#555555" />
    </mesh>
  )
}

const CROSS_CENTER = HALF + 2.5   // crosswalk band centre (matches engine CROSSWALK_CENTER)
const CROSS_DEPTH = 3
const STOP_DIST = CROSS_CENTER + CROSS_DEPTH / 2 + 1   // stop line distance from centre (matches engine)
const CROSS_WIDTH = 12                                   // pedestrians walk 12 m

const FLAT = [-Math.PI / 2, 0, 0]

function LaneMarkings() {
  const lines = []
  const step = 6
  const end = ARM_LENGTH - 2

  for (let d = STOP_DIST + 3; d < end; d += step) {
    lines.push(
      <mesh key={`n-${d}`} rotation={FLAT} position={[0, 0.01, -(d + 1.5)]}><planeGeometry args={[0.2, 3]} /><meshBasicMaterial color="#ffffff" /></mesh>,
      <mesh key={`s-${d}`} rotation={FLAT} position={[0, 0.01, d + 1.5]}><planeGeometry args={[0.2, 3]} /><meshBasicMaterial color="#ffffff" /></mesh>,
      <mesh key={`e-${d}`} rotation={FLAT} position={[d + 1.5, 0.01, 0]}><planeGeometry args={[3, 0.2]} /><meshBasicMaterial color="#ffffff" /></mesh>,
      <mesh key={`w-${d}`} rotation={FLAT} position={[-(d + 1.5), 0.01, 0]}><planeGeometry args={[3, 0.2]} /><meshBasicMaterial color="#ffffff" /></mesh>,
    )
  }

  // stop lines: only across the INBOUND lane of each arm, exactly where the simulation stops the bumper
  lines.push(
    <mesh key="sl-n" rotation={FLAT} position={[-LANE_WIDTH / 2, 0.012, -STOP_DIST]}><planeGeometry args={[LANE_WIDTH, 0.4]} /><meshBasicMaterial color="#ffffff" /></mesh>,
    <mesh key="sl-s" rotation={FLAT} position={[LANE_WIDTH / 2, 0.012, STOP_DIST]}><planeGeometry args={[LANE_WIDTH, 0.4]} /><meshBasicMaterial color="#ffffff" /></mesh>,
    <mesh key="sl-e" rotation={FLAT} position={[STOP_DIST, 0.012, -LANE_WIDTH / 2]}><planeGeometry args={[0.4, LANE_WIDTH]} /><meshBasicMaterial color="#ffffff" /></mesh>,
    <mesh key="sl-w" rotation={FLAT} position={[-STOP_DIST, 0.012, LANE_WIDTH / 2]}><planeGeometry args={[0.4, LANE_WIDTH]} /><meshBasicMaterial color="#ffffff" /></mesh>,
  )
  return <group>{lines}</group>
}

function ZebraCrossings() {
  const stripes = []
  const count = 10
  for (let i = 0; i < count; i++) {
    const o = -CROSS_WIDTH / 2 + 0.6 + i * (CROSS_WIDTH / count)
    stripes.push(
      <mesh key={`zn-${i}`} rotation={FLAT} position={[o, 0.011, -CROSS_CENTER]}><planeGeometry args={[0.6, CROSS_DEPTH]} /><meshBasicMaterial color="#e5e7eb" /></mesh>,
      <mesh key={`zs-${i}`} rotation={FLAT} position={[o, 0.011, CROSS_CENTER]}><planeGeometry args={[0.6, CROSS_DEPTH]} /><meshBasicMaterial color="#e5e7eb" /></mesh>,
      <mesh key={`ze-${i}`} rotation={FLAT} position={[CROSS_CENTER, 0.011, o]}><planeGeometry args={[CROSS_DEPTH, 0.6]} /><meshBasicMaterial color="#e5e7eb" /></mesh>,
      <mesh key={`zw-${i}`} rotation={FLAT} position={[-CROSS_CENTER, 0.011, o]}><planeGeometry args={[CROSS_DEPTH, 0.6]} /><meshBasicMaterial color="#e5e7eb" /></mesh>,
    )
  }
  return <group>{stripes}</group>
}

// pavement strips next to the asphalt so the 12 m crosswalks start and end on a sidewalk
function Sidewalks() {
  const len = ARM_LENGTH - HALF
  const mid = HALF + len / 2
  const off = ROAD_WIDTH / 2 + 2
  const mat = <meshLambertMaterial color="#9ca3af" />
  const quads = []
  for (const sx of [-1, 1]) {
    quads.push(
      <mesh key={`ns-a${sx}`} rotation={FLAT} position={[sx * off, 0.005, -mid]}><planeGeometry args={[4, len]} />{mat}</mesh>,
      <mesh key={`ns-b${sx}`} rotation={FLAT} position={[sx * off, 0.005, mid]}><planeGeometry args={[4, len]} />{mat}</mesh>,
      <mesh key={`ew-a${sx}`} rotation={FLAT} position={[-mid, 0.005, sx * off]}><planeGeometry args={[len, 4]} />{mat}</mesh>,
      <mesh key={`ew-b${sx}`} rotation={FLAT} position={[mid, 0.005, sx * off]}><planeGeometry args={[len, 4]} />{mat}</mesh>,
    )
    for (const sz of [-1, 1]) {
      quads.push(<mesh key={`c${sx}${sz}`} rotation={FLAT} position={[sx * (HALF + 2), 0.005, sz * (HALF + 2)]}><planeGeometry args={[4, 4]} />{mat}</mesh>)
    }
  }
  return <group>{quads}</group>
}
