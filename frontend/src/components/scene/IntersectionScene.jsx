/**
 * IntersectionScene — R3F Canvas root.
 * Renders all 3D objects from simulation state.
 */
import { Canvas } from '@react-three/fiber'
import { OrbitControls, Stars } from '@react-three/drei'
import RoadSystem from './RoadSystem'
import VehicleModel from './VehicleModel'
import PedestrianModel from './PedestrianModel'
import TrafficLightModel from './TrafficLightModel'
import SceneEnvironment from './SceneEnvironment'

export default function IntersectionScene({ vehicles = [], pedestrians = [], lights = [] }) {
  return (
    <Canvas
      shadows
      camera={{ position: [0, 90, 90], fov: 45, near: 0.1, far: 1000 }}
      style={{ background: '#87ceeb' }}
    >
      {/* Controls */}
      <OrbitControls
        target={[0, 0, 0]}
        maxPolarAngle={Math.PI / 2.1}
        minDistance={20}
        maxDistance={300}
      />

      {/* Lighting */}
      <ambientLight intensity={0.6} />
      <directionalLight
        castShadow
        position={[50, 100, 50]}
        intensity={1.2}
        shadow-mapSize-width={2048}
        shadow-mapSize-height={2048}
        shadow-camera-near={0.5}
        shadow-camera-far={500}
        shadow-camera-left={-150}
        shadow-camera-right={150}
        shadow-camera-top={150}
        shadow-camera-bottom={-150}
      />

      {/* Scene */}
      <SceneEnvironment />
      <RoadSystem />

      {/* Traffic lights */}
      {lights.map(l => (
        <TrafficLightModel key={l.id} {...l} />
      ))}

      {/* Vehicles */}
      {vehicles.map(v => (
        <VehicleModel key={v.id} {...v} />
      ))}

      {/* Pedestrians */}
      {pedestrians.map(p => (
        <PedestrianModel key={p.id} {...p} />
      ))}
    </Canvas>
  )
}
