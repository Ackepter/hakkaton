/**
 * CameraModel — the virtual overhead camera as an object in the 3D scene: a mast with a camera head and the outline
 * of its field of view on the ground (the area that is rendered into the camera picture and analysed).
 * Green = healthy, red = signal lost / disconnected.
 */
import { Line, Html } from '@react-three/drei'

const VIEW_RADIUS = 64
const MAST = [-11, 0, -11]

export default function CameraModel({ camera, healthy }) {
  const color = healthy ? '#22c55e' : '#ef4444'
  const r = VIEW_RADIUS
  const outline = [[-r, 0.05, -r], [r, 0.05, -r], [r, 0.05, r], [-r, 0.05, r], [-r, 0.05, -r]]

  return (
    <group>
      <Line points={outline} color={color} lineWidth={1} dashed dashSize={3} gapSize={3} transparent opacity={0.7} />
      <group position={MAST}>
        <mesh position={[0, 8, 0]} castShadow>
          <cylinderGeometry args={[0.2, 0.25, 16, 8]} />
          <meshLambertMaterial color="#6b7280" />
        </mesh>
        <group position={[0, 16.4, 0]} rotation={[0, Math.PI / 4, -0.5]}>
          <mesh castShadow>
            <boxGeometry args={[1.6, 0.9, 0.9]} />
            <meshLambertMaterial color="#1f2937" />
          </mesh>
          <mesh position={[0.9, 0, 0]} rotation={[0, 0, Math.PI / 2]}>
            <cylinderGeometry args={[0.32, 0.32, 0.3, 12]} />
            <meshStandardMaterial color={color} emissive={color} emissiveIntensity={1.2} />
          </mesh>
        </group>
        <Html position={[0, 19, 0]} center distanceFactor={90} style={{ pointerEvents: 'none' }}>
          <div style={{ background: 'rgba(0,0,0,0.65)', color: '#fff', fontSize: 11, padding: '2px 6px', borderRadius: 4,
                        whiteSpace: 'nowrap', border: `1px solid ${color}` }}>
            {camera ? `${camera.id} · ${camera.state}` : 'CAM'}
          </div>
        </Html>
      </group>
    </group>
  )
}
