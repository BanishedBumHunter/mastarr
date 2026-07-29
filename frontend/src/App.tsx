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
import Activity from './pages/Activity'
import Calendar from './pages/Calendar'
import Dashboard from './pages/Dashboard'
import Discover from './pages/Discover'
import Library from './pages/Library'
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
          { to: '/', label: 'Library' },
          { to: '/calendar', label: 'Calendar' },
          { to: '/discover', label: 'Discover' },
          { to: '/requests', label: 'Requests' },
          { to: '/activity', label: 'Activity' },
          { to: '/dashboard', label: 'Services' },
        ]}
      />
      <main className="content">
        <Routes>
          {/* Library is the landing page: it's what you actually came to look at.
              The old status dashboard moves to /dashboard alongside service config. */}
          <Route path="/" element={<Library />} />
          <Route path="/calendar" element={<Calendar />} />
          <Route path="/discover" element={<Discover />} />
          <Route path="/requests" element={<Requests />} />
          <Route path="/activity" element={<Activity />} />
          <Route path="/dashboard" element={<Dashboard />} />
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
      <TopBar
        links={[
          { to: '/', label: 'Discover' },
          { to: '/requests', label: 'My requests' },
          { to: '/calendar', label: 'Calendar' },
        ]}
      />
      <main className="content">
        <Routes>
          <Route path="/" element={<Discover />} />
          <Route path="/requests" element={<Requests />} />
          <Route path="/calendar" element={<Calendar />} />
          {/* No admin routes exist in this tree at all — not hidden, absent. */}
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
