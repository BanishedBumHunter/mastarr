/**
 * App shell and role-based routing.
 *
 * The two role trees are genuinely separate `<Routes>` blocks. A Requester's app contains
 * no admin routes — not hidden, not disabled, not rendered-and-guarded. If the role check
 * here were somehow bypassed, the admin routes still would not exist to navigate to, and
 * the backend would reject the API calls regardless.
 */

import { NavLink, Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth'
import Dashboard from './pages/Dashboard'
import Login from './pages/Login'
import Requests from './pages/Requests'
import Services from './pages/Services'
import Users from './pages/Users'

function TopBar({ links }: { links: { to: string; label: string }[] }) {
  const { user, logout } = useAuth()
  return (
    <header className="topbar">
      <div className="brand">
        mast<span>arr</span>
      </div>
      <nav className="nav">
        {links.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            className={({ isActive }) => (isActive ? 'active' : '')}
          >
            {link.label}
          </NavLink>
        ))}
      </nav>
      <div className="topbar-right">
        <span>
          {user?.username} · {user?.role}
        </span>
        <button className="small" onClick={() => void logout()}>
          Sign out
        </button>
      </div>
    </header>
  )
}

function AdminApp() {
  return (
    <div className="app">
      <TopBar
        links={[
          { to: '/', label: 'Dashboard' },
          { to: '/services', label: 'Services' },
          { to: '/users', label: 'Users' },
        ]}
      />
      <main className="content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/services" element={<Services />} />
          <Route path="/users" element={<Users />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}

function RequesterApp() {
  return (
    <div className="app">
      <TopBar links={[{ to: '/', label: 'Requests' }]} />
      <main className="content">
        <Routes>
          <Route path="/" element={<Requests />} />
          {/* No admin routes exist in this tree at all. */}
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}

export default function App() {
  const { state, loading, isAdmin } = useAuth()

  if (loading) {
    return (
      <div className="auth-screen">
        <span className="spinner" />
      </div>
    )
  }

  if (state?.needs_setup) return <Login mode="setup" />
  if (!state?.authenticated) return <Login mode="login" />

  return isAdmin ? <AdminApp /> : <RequesterApp />
}
