/**
 * CameraModel — a virtual camera on its mast, with the volume it sees.
 *
 * The camera is a pinhole: position (x, z), height, heading (compass yaw), tilt (pitch) and horizontal field of view
 * (builder/geometry.js mirrors backend/vision/camera_model.py). The dashed quadrilateral on the ground is where the
 * corners of the picture land (limited by the range); lines run from the lens to its corners.
 * Green = the camera delivers frames, red = signal lost / disconnected, grey = switched off.
 */
import { useMemo } from 'react'
import { DoubleSide, BufferGeometry, Euler, Float32BufferAttribute } from 'three'
import { Line, Html } from '@react-three/drei'
import { cameraAim, cameraFootprint } from '../../builder/geometry'

export default function CameraModel({ cam, label, healthy = true, selected = false, dim = false, pickable = false,
                                      overhead = false, ...events }) {
  const color = dim ? '#94a3b8' : healthy ? '#22c55e' : '#ef4444'
  const h = cam.height_m ?? 12
  const [yaw, pitch] = cameraAim(cam)
  const foot = useMemo(() => cameraFootprint(cam), [cam.x, cam.z, cam.height_m, cam.fov_deg, cam.radius_m, cam.yaw_deg, cam.pitch_deg])   // eslint-disable-line react-hooks/exhaustive-deps
  const outline = [...foot, foot[0]].map(([x, z]) => [x, 0.25, z])
  const fill = useMemo(() => {
    const g = new BufferGeometry()
    const p = foot.flatMap(([x, z]) => [x, 0.22, z])
    g.setAttribute('position', new Float32BufferAttribute([...p.slice(0, 3), ...p.slice(3, 6), ...p.slice(6, 9), ...p.slice(0, 3), ...p.slice(6, 9), ...p.slice(9, 12)], 3))
    return g
  }, [foot])
  const rot = useMemo(() => new Euler((-pitch * Math.PI) / 180, (-yaw * Math.PI) / 180, 0, 'YXZ'), [yaw, pitch])
  return (
    <group>
      <mesh geometry={fill}><meshBasicMaterial color={selected ? '#facc15' : color} transparent opacity={dim ? 0.05 : 0.13} side={DoubleSide} depthWrite={false} /></mesh>
      <Line points={outline} color={selected ? '#facc15' : color} lineWidth={selected ? 2 : 1} dashed dashSize={3} gapSize={3}
            transparent opacity={dim ? 0.35 : 0.8} />
      {foot.map(([x, z], i) => (
        <Line key={i} points={[[cam.x, h, cam.z], [x, 0.25, z]]} color={color} lineWidth={0.6} transparent opacity={dim ? 0.15 : 0.35} />
      ))}
      <group position={[cam.x, 0, cam.z]} {...events}>
        {pickable && (
          <mesh position={[0, h / 2, 0]}>
            <cylinderGeometry args={[1.6, 1.6, h, 10]} /><meshBasicMaterial transparent opacity={0} depthWrite={false} />
          </mesh>
        )}
        <mesh position={[0, h / 2, 0]} castShadow><cylinderGeometry args={[0.2, 0.25, h, 8]} /><meshLambertMaterial color={overhead ? '#94a3b8' : '#6b7280'} /></mesh>
        <group position={[0, h, 0]} rotation={rot}>
          <mesh castShadow><boxGeometry args={[0.9, 0.9, 1.6]} /><meshLambertMaterial color="#1f2937" /></mesh>
          <mesh position={[0, 0, -0.9]} rotation={[Math.PI / 2, 0, 0]}>
            <cylinderGeometry args={[0.32, 0.32, 0.3, 12]} />
            <meshStandardMaterial color={color} emissive={color} emissiveIntensity={1.2} />
          </mesh>
        </group>
        {selected && (
          <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.2, 0]}>
            <ringGeometry args={[1.2, 1.6, 32]} /><meshBasicMaterial color="#facc15" side={2} />
          </mesh>
        )}
        <Html position={[0, h + 3, 0]} center distanceFactor={90} style={{ pointerEvents: 'none' }}>
          <div style={{ background: 'rgba(0,0,0,0.65)', color: '#fff', fontSize: 11, padding: '2px 6px', borderRadius: 4,
                        whiteSpace: 'nowrap', border: `1px solid ${color}` }}>{label} · {Math.round(cam.fov_deg ?? 70)}°</div>
        </Html>
      </group>
    </group>
  )
}
