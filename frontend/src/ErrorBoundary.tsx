/**
 * Last-resort error boundary.
 *
 * The degradation contract is enforced in the backend — every service snapshot is total,
 * so a dead *arr produces a card rather than a thrown error. This boundary exists for
 * genuine frontend bugs, so that even then the user gets a readable page and a recovery
 * action instead of a blank screen.
 */

import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

interface State {
  error: Error | null
}

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Unhandled UI error', error, info)
  }

  render() {
    if (!this.state.error) return this.props.children

    return (
      <div className="auth-screen">
        <div className="auth-box">
          <div className="brand">
            mast<span>arr</span>
          </div>
          <p className="subtle">Something went wrong rendering this page.</p>
          <div className="error-box">{this.state.error.message}</div>
          <button className="primary" onClick={() => window.location.reload()}>
            Reload
          </button>
        </div>
      </div>
    )
  }
}
