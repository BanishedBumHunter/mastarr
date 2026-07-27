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
  const [form, setForm] = useState<{ username: string; password: string; role: Role }>({
    username: '',
    password: '',
    role: 'requester',
  })

  const { data: users, isLoading, error } = useQuery({ queryKey: ['users'], queryFn: api.users })
  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['users'] })

  const create = useMutation({
    mutationFn: () => api.createUser(form),
    onSuccess: async () => {
      setForm({ username: '', password: '', role: 'requester' })
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
