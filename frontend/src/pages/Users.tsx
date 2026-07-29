/** User management. Admin-only — this module is never loaded into a Requester's tree. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api'
import type { Role } from '../api'
import { ErrorBox, Spinner } from '../components'
import { useAuth } from '../auth'

export default function Users() {
  const queryClient = useQueryClient()
  const { user: me } = useAuth()
  const [form, setForm] = useState<{
    username: string
    password: string
    role: Role
    jellyseerr_user_id: number | null
  }>({ username: '', password: '', role: 'requester', jellyseerr_user_id: null })

  // Jellyseerr accounts, so a Mastarr user's requests are attributed to the right person.
  // Absent (or erroring) simply means no Jellyseerr is connected — not a failure worth
  // showing, so the picker just doesn't appear.
  const jellyseerrUsers = useQuery({
    queryKey: ['jellyseerr-users'],
    queryFn: api.jellyseerrUsers,
    retry: false,
  })
  const linkable = jellyseerrUsers.data ?? []

  const { data: users, isLoading, error } = useQuery({ queryKey: ['users'], queryFn: api.users })
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['users'] })

  const create = useMutation({
    mutationFn: () => api.createUser(form),
    onSuccess: async () => {
      setForm({ username: '', password: '', role: 'requester', jellyseerr_user_id: null })
      await invalidate()
    },
  })
  const remove = useMutation({ mutationFn: api.deleteUser, onSuccess: invalidate })
  const update = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Record<string, unknown> }) =>
      api.updateUser(id, data),
    onSuccess: invalidate,
  })

  return (
    <>
      <div className="page-head">
        <h1>Users</h1>
      </div>

      <div className="stack">
        <div className="section">
          <h2>Create user</h2>
          <div className="form-row">
            <div>
              <label htmlFor="uname">Username</label>
              <input
                id="uname"
                value={form.username}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, username: event.target.value }))
                }
              />
            </div>
            <div>
              <label htmlFor="upass">Password</label>
              <input
                id="upass"
                type="password"
                value={form.password}
                placeholder="At least 8 characters"
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, password: event.target.value }))
                }
              />
            </div>
            <div>
              <label htmlFor="urole">Role</label>
              <select
                id="urole"
                value={form.role}
                onChange={(event) =>
                  setForm((prev) => ({ ...prev, role: event.target.value as Role }))
                }
              >
                <option value="requester">Requester</option>
                <option value="admin">Admin</option>
              </select>
            </div>
            {linkable.length > 0 ? (
              <div>
                <label htmlFor="ujs">Jellyseerr account</label>
                <select
                  id="ujs"
                  value={form.jellyseerr_user_id ?? ''}
                  onChange={(event) =>
                    setForm((prev) => ({
                      ...prev,
                      jellyseerr_user_id: event.target.value
                        ? Number(event.target.value)
                        : null,
                    }))
                  }
                >
                  <option value="">Not linked</option>
                  {linkable.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.display_name}
                    </option>
                  ))}
                </select>
              </div>
            ) : null}
            <button
              className="primary"
              onClick={() => create.mutate()}
              disabled={create.isPending || !form.username || form.password.length < 8}
            >
              Create
            </button>
          </div>
          <p className="subtle" style={{ marginBottom: 0 }}>
            <b>Admins</b> manage the whole stack. <b>Requesters</b> can only browse and
            request media, and see just their own requests.
            {linkable.length > 0
              ? ' Link a Requester to a Jellyseerr account so their requests are attributed to them — without it, their request list stays empty.'
              : ''}
          </p>
          {create.error ? <ErrorBox>{(create.error as Error).message}</ErrorBox> : null}
        </div>

        <div className="section">
          <h2>Accounts</h2>
          {isLoading ? <Spinner label="Loading…" /> : null}
          {error ? <ErrorBox>{(error as Error).message}</ErrorBox> : null}

          {users ? (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Username</th>
                    <th>Role</th>
                    {linkable.length > 0 ? <th>Jellyseerr</th> : null}
                    <th>Status</th>
                    <th>Created</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {users.map((user) => (
                    <tr key={user.id}>
                      <td>
                        {user.username}
                        {user.id === me?.id ? (
                          <span className="badge plain" style={{ marginLeft: 6 }}>
                            you
                          </span>
                        ) : null}
                      </td>
                      <td>
                        <span className={`badge ${user.role === 'admin' ? 'online' : 'plain'}`}>
                          {user.role}
                        </span>
                      </td>
                      {linkable.length > 0 ? (
                        <td>
                          <select
                            value={user.jellyseerr_user_id ?? ''}
                            disabled={update.isPending}
                            onChange={(event) =>
                              update.mutate({
                                id: user.id,
                                data: {
                                  // 0 unlinks — the backend treats it as "clear".
                                  jellyseerr_user_id: event.target.value
                                    ? Number(event.target.value)
                                    : 0,
                                },
                              })
                            }
                          >
                            <option value="">Not linked</option>
                            {linkable.map((u) => (
                              <option key={u.id} value={u.id}>
                                {u.display_name}
                              </option>
                            ))}
                          </select>
                        </td>
                      ) : null}
                      <td className="subtle">{user.is_active ? 'active' : 'disabled'}</td>
                      <td className="subtle">
                        {new Date(user.created_at).toLocaleDateString()}
                      </td>
                      <td>
                        <div className="row">
                          <button
                            className="small"
                            disabled={update.isPending}
                            onClick={() =>
                              update.mutate({
                                id: user.id,
                                data: { is_active: !user.is_active },
                              })
                            }
                          >
                            {user.is_active ? 'Disable' : 'Enable'}
                          </button>
                          <button
                            className="small danger"
                            disabled={user.id === me?.id || remove.isPending}
                            onClick={() => remove.mutate(user.id)}
                          >
                            Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          {update.error ? <ErrorBox>{(update.error as Error).message}</ErrorBox> : null}
          {remove.error ? <ErrorBox>{(remove.error as Error).message}</ErrorBox> : null}
        </div>
      </div>
    </>
  )
}
