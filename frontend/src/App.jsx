import { BrowserRouter, Routes, Route, Navigate, NavLink } from 'react-router-dom'
import { Box, LayoutDashboard, TrafficCone } from 'lucide-react'
import Dashboard from './pages/Dashboard'
import Simulation3D from './pages/Simulation3D'
import { cn } from '@/lib/utils'

const NAV_ITEMS = [
  { to: '/simulation', label: '3D Simulation', icon: Box },
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
]

export const SIDEBAR_W = 224
export const HEADER_H = 56

function Sidebar() {
  return (
    <aside
      className="fixed inset-y-0 left-0 flex flex-col border-r border-border bg-card"
      style={{ width: SIDEBAR_W }}
    >
      <div className="flex items-center gap-2 px-4 border-b border-border" style={{ height: HEADER_H }}>
        <TrafficCone className="h-5 w-5 text-primary" />
        <span className="font-semibold text-sm tracking-wide">Smart Intersection</span>
      </div>
      <nav className="flex flex-col gap-1 p-2">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground',
                isActive && 'bg-accent text-foreground'
              )
            }
          >
            <Icon className="h-4 w-4" />
            {label}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <Sidebar />
      <div style={{ marginLeft: SIDEBAR_W }}>
        <Routes>
          <Route path="/" element={<Navigate to="/simulation" replace />} />
          <Route path="/simulation" element={<Simulation3D />} />
          <Route path="/dashboard" element={<Dashboard />} />
        </Routes>
      </div>
    </BrowserRouter>
  )
}
