/**
 * Auth context.
 *
 * The state fetched here decides which *route tree* is mounted — see main.tsx. A Requester
 * never receives admin routes at all; there is no admin component rendered-then-hidden.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from './api'
import type { AuthState, User } from './api'

interface AuthContextValue {
  state: AuthState | null
  loading: boolean
  user: User | null
  isAdmin: boolean
  refresh: () => Promise<void>
  login: (username: string, password: string) => Promise<void>
  setup: (username: string, password: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      setState(await api.authState())
    } catch {
      // A failed bootstrap must not leave a blank screen — treat it as signed out.
      setState({ needs_setup: false, authenticated: false, user: null })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const value = useMemo<AuthContextValue>(
    () => ({
      state,
      loading,
      user: state?.user ?? null,
      isAdmin: state?.user?.role === 'admin',
      refresh,
      login: async (username, password) => {
        await api.login(username, password)
        await refresh()
      },
      setup: async (username, password) => {
        await api.setup(username, password)
        await refresh()
      },
      logout: async () => {
        await api.logout()
        await refresh()
      },
    }),
    [state, loading, refresh],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext)
  if (!context) throw new Error('useAuth must be used inside AuthProvider')
  return context
}
