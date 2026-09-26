/**
 * Decoration objects of the city (buildings, trees, lamps ...) drawn from primitives.
 * The same components render the play view, the build view, and the translucent "ghost" of a tool being placed.
 */
import { SCENE_TYPES } from '../../builder/geometry'

const RAD = Math.PI / 180

function Mat({ color, opacity = 1, emissive, emissiveIntensity = 0 }) {
  return <meshLambertMaterial color={color} transparent={opacity < 1} opacity={opacity}
                              emissive={emissive || '#000000'} emissiveIntensity={emissiveIntensity} />
}

function Building({ o, opacity }) {
  const w = 10 * o.scale
  const h = o.height ?? 12
  const color = o.color || '#7c8fb0'
  return (
    <group>
      <mesh position={[0, h / 2, 0]} castShadow receiveShadow><boxGeometry args={[w, h, w]} /><Mat color={color} opacity={opacity} /></mesh>
      <mesh position={[0, h + 0.25, 0]}><boxGeometry args={[w + 0.4, 0.5, w + 0.4]} /><Mat color="#475569" opacity={opacity} /></mesh>
      {Array.from({ length: Math.max(1, Math.floor(h / 4)) }, (_, i) => (
        <mesh key={i} position={[0, 2 + i * 4, w / 2 + 0.02]}><planeGeometry args={[w * 0.8, 1.1]} />
          <meshBasicMaterial color="#cfe8ff" transparent opacity={0.55 * opacity} /></mesh>
      ))}
    </group>
  )
}

function House({ o, opacity }) {
  const color = o.color || '#d4a373'
  const h = o.height ? Math.min(o.height, 9) : 4
  return (
    <group scale={[o.scale, o.scale, o.scale]}>
      <mesh position={[0, h / 2, 0]} castShadow><boxGeometry args={[6, h, 6]} /><Mat color={color} opacity={opacity} /></mesh>
      <mesh position={[0, h + 1.3, 0]} rotation={[0, Math.PI / 4, 0]} castShadow>
        <coneGeometry args={[5.2, 2.6, 4]} /><Mat color="#9a3412" opacity={opacity} />
      </mesh>
    </group>
  )
}

function Tree({ o, opacity }) {
  return (
    <group scale={[o.scale, o.scale, o.scale]}>
      <mesh position={[0, 1.2, 0]} castShadow><cylinderGeometry args={[0.2, 0.3, 2.4, 6]} /><Mat color="#8B4513" opacity={opacity} /></mesh>
      <mesh position={[0, 3.5, 0]} castShadow><sphereGeometry args={[1.8, 8, 6]} /><Mat color={o.color || '#3f8f4a'} opacity={opacity} /></mesh>
    </group>
  )
}

function Lamp({ o, opacity }) {
  return (
    <group scale={[o.scale, o.scale, o.scale]}>
      <mesh position={[0, 3, 0]} castShadow><cylinderGeometry args={[0.1, 0.14, 6, 8]} /><Mat color="#4b5563" opacity={opacity} /></mesh>
      <mesh position={[0.6, 5.9, 0]}><boxGeometry args={[1.4, 0.12, 0.12]} /><Mat color="#4b5563" opacity={opacity} /></mesh>
      <mesh position={[1.2, 5.75, 0]}><sphereGeometry args={[0.28, 10, 8]} />
        <Mat color="#fde68a" opacity={opacity} emissive="#fde68a" emissiveIntensity={0.9} /></mesh>
    </group>
  )
}

function BusStop({ o, opacity }) {
  return (
    <group scale={[o.scale, o.scale, o.scale]}>
      {[-1.2, 1.2].map(x => (
        <mesh key={x} position={[x, 1.3, -0.5]} castShadow><boxGeometry args={[0.1, 2.6, 0.1]} /><Mat color="#374151" opacity={opacity} /></mesh>
      ))}
      <mesh position={[0, 2.65, 0]} castShadow><boxGeometry args={[3, 0.12, 1.6]} /><Mat color="#dc2626" opacity={opacity} /></mesh>
      <mesh position={[0, 1.3, -0.5]}><boxGeometry args={[2.4, 1.6, 0.05]} />
        <meshBasicMaterial color="#bae6fd" transparent opacity={0.4 * opacity} /></mesh>
      <mesh position={[0, 0.5, -0.2]}><boxGeometry args={[2, 0.1, 0.5]} /><Mat color="#92400e" opacity={opacity} /></mesh>
      <mesh position={[1.9, 1.6, 0.4]}><boxGeometry args={[0.06, 3.2, 0.06]} /><Mat color="#374151" opacity={opacity} /></mesh>
      <mesh position={[1.9, 3.1, 0.4]}><boxGeometry args={[0.7, 0.6, 0.06]} /><Mat color="#2563eb" opacity={opacity} /></mesh>
    </group>
  )
}

function Bench({ o, opacity }) {
  return (
    <group scale={[o.scale, o.scale, o.scale]}>
      <mesh position={[0, 0.45, 0]} castShadow><boxGeometry args={[1.8, 0.1, 0.5]} /><Mat color="#92400e" opacity={opacity} /></mesh>
      <mesh position={[0, 0.85, -0.22]}><boxGeometry args={[1.8, 0.4, 0.06]} /><Mat color="#92400e" opacity={opacity} /></mesh>
      {[-0.8, 0.8].map(x => (
        <mesh key={x} position={[x, 0.22, 0]}><boxGeometry args={[0.08, 0.44, 0.45]} /><Mat color="#374151" opacity={opacity} /></mesh>
      ))}
    </group>
  )
}

function Fence({ o, opacity }) {
  return (
    <group scale={[o.scale, o.scale, o.scale]}>
      {[-1.8, -0.6, 0.6, 1.8].map(x => (
        <mesh key={x} position={[x, 0.6, 0]} castShadow><boxGeometry args={[0.12, 1.2, 0.12]} /><Mat color="#a16207" opacity={opacity} /></mesh>
      ))}
      {[0.4, 0.9].map(y => (
        <mesh key={y} position={[0, y, 0]}><boxGeometry args={[4, 0.1, 0.06]} /><Mat color="#ca8a04" opacity={opacity} /></mesh>
      ))}
    </group>
  )
}

function Kiosk({ o, opacity }) {
  return (
    <group scale={[o.scale, o.scale, o.scale]}>
      <mesh position={[0, 1.2, 0]} castShadow><boxGeometry args={[3, 2.4, 2.4]} /><Mat color={o.color || '#0ea5e9'} opacity={opacity} /></mesh>
      <mesh position={[0, 2.6, 0.2]}><boxGeometry args={[3.4, 0.2, 3]} /><Mat color="#f97316" opacity={opacity} /></mesh>
      <mesh position={[0, 1.4, 1.22]}><planeGeometry args={[2, 0.9]} /><meshBasicMaterial color="#fef9c3" transparent opacity={0.8 * opacity} /></mesh>
    </group>
  )
}

const MODELS = { building: Building, house: House, tree: Tree, lamp: Lamp, bus_stop: BusStop, bench: Bench, fence: Fence, kiosk: Kiosk }

/** One object. `ring` = 'selected' | 'valid' | 'invalid' draws a marker on the ground under it. */
export default function SceneryObject({ obj, opacity = 1, ring = null, pickable = false, ...events }) {
  const Model = MODELS[obj.type]
  if (!Model) return null
  const r = SCENE_TYPES[obj.type].radius * obj.scale
  const ringColor = { selected: '#facc15', valid: '#22c55e', invalid: '#ef4444' }[ring]
  return (
    <group position={[obj.x, 0, obj.z]} rotation={[0, -(obj.rotation_deg || 0) * RAD, 0]} {...events}>
      <Model o={obj} opacity={opacity} />
      {/* generous invisible hit area: small objects stay easy to click */}
      {pickable && (
        <mesh position={[0, Math.max(3, obj.height ?? 0) / 2, 0]}>
          <cylinderGeometry args={[Math.max(r, 1.2), Math.max(r, 1.2), Math.max(3, obj.height ?? 0), 12]} />
          <meshBasicMaterial transparent opacity={0} depthWrite={false} />
        </mesh>
      )}
      {ring && (
        <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.2, 0]}>
          <ringGeometry args={[r * 1.02, r * 1.02 + 0.35, 40]} />
          <meshBasicMaterial color={ringColor} side={2} transparent opacity={0.9} />
        </mesh>
      )}
    </group>
  )
}

export function SceneryLayer({ objects }) {
  return <group>{objects.map(o => <SceneryObject key={o.id} obj={o} />)}</group>
}
