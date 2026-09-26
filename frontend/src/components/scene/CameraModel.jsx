/**
 * CameraModel — a virtual camera on a mast, with the outline of its field of view on the ground.
 * Green = the camera delivers frames, red = signal lost / disconnected. Placed by the constructor or, when the
 * layout has no cameras, the default overhead camera (mast in a corner, looking at the whole crossing).
 */
import { Line, Html } from '@react-three/drei'

export default function CameraModel({ label, mast, view, radius, healthy = true, selected = false, dim = false, pickable = false, ...events }) {
  const color = dim ? '#94a3b8' : healthy ? '#22c55e' : '#ef4444'
  const [cx, cz] = view
  const r = radius
  const outline = [[cx - r, 0.2, cz - r], [cx + r, 0.2, cz - r], [cx + r, 0.2, cz + r], [cx - r, 0.2, cz + r], [cx - r, 0.2, cz - r]]
  return (
    <group>
      <Line points={outline} color={selected ? '#facc15' : color} lineWidth={selected ? 2 : 1} dashed dashSize={3} gapSize={3}
            transparent opacity={dim ? 0.35 : 0.75} />
      <group position={[mast[0], 0, mast[1]]} {...events}>
        {pickable && (
          <mesh position={[0, 9, 0]}>
            <cylinderGeometry args={[1.6, 1.6, 18, 10]} /><meshBasicMaterial transparent opacity={0} depthWrite={false} />
          </mesh>
        )}
        <mesh position={[0, 8, 0]} castShadow><cylinderGeometry args={[0.2, 0.25, 16, 8]} /><meshLambertMaterial color="#6b7280" /></mesh>
        <group position={[0, 16.4, 0]} rotation={[0, Math.PI / 4, -0.5]}>
          <mesh castShadow><boxGeometry args={[1.6, 0.9, 0.9]} /><meshLambertMaterial color="#1f2937" /></mesh>
          <mesh position={[0.9, 0, 0]} rotation={[0, 0, Math.PI / 2]}>
            <cylinderGeometry args={[0.32, 0.32, 0.3, 12]} />
            <meshStandardMaterial color={color} emissive={color} emissiveIntensity={1.2} />
          </mesh>
        </group>
        {selected && (
          <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.2, 0]}>
            <ringGeometry args={[1.2, 1.6, 32]} /><meshBasicMaterial color="#facc15" side={2} />
          </mesh>
        )}
        <Html position={[0, 19, 0]} center distanceFactor={90} style={{ pointerEvents: 'none' }}>
          <div style={{ background: 'rgba(0,0,0,0.65)', color: '#fff', fontSize: 11, padding: '2px 6px', borderRadius: 4,
                        whiteSpace: 'nowrap', border: `1px solid ${color}` }}>{label}</div>
        </Html>
      </group>
    </group>
  )
}
