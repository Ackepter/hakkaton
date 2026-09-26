import { BrowserRouter, Routes, Route, NavLink } from 'react-router-dom'
import Constructor from './pages/Constructor'
import Dashboard from './pages/Dashboard'
import Simulation3D from './pages/Simulation3D'

const styles = {
  nav: {
    display: 'flex', alignItems: 'center', gap: 8,
    background: '#1a1d27', borderBottom: '1px solid #2d3748',
    padding: '0 24px', height: 56,
  },
  brand: { color: '#63b3ed', fontWeight: 700, fontSize: 18, marginRight: 24, letterSpacing: 0.5 },
  link: {
    color: '#a0aec0', textDecoration: 'none', padding: '8px 16px',
    borderRadius: 6, fontSize: 14, fontWeight: 500, transition: 'all 0.15s',
  },
  activeLink: {
    color: '#fff', background: '#2d3748',
  },
}

export default function App() {
  return (
    <BrowserRouter>
      <nav style={styles.nav}>
        <span style={styles.brand}>🚦 Smart Intersection</span>
        <NavLink to="/" end style={({ isActive }) => ({ ...styles.link, ...(isActive ? styles.activeLink : {}) })}>
          Конструктор
        </NavLink>
        <NavLink to="/dashboard" style={({ isActive }) => ({ ...styles.link, ...(isActive ? styles.activeLink : {}) })}>
          Dashboard
        </NavLink>
        <NavLink to="/simulation" style={({ isActive }) => ({ ...styles.link, ...(isActive ? styles.activeLink : {}) })}>
          3D Simulation
        </NavLink>
      </nav>
      <Routes>
        <Route path="/" element={<Constructor />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/simulation" element={<Simulation3D />} />
      </Routes>
    </BrowserRouter>
  )
}
