import { Component, type ReactNode } from 'react'

interface State {
  error: Error | null
}

export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  render() {
    if (this.state.error) {
      return (
        <main className="page">
          <div className="notice notice-err" role="alert">
            <strong>Something went wrong.</strong>
            <p>
              Please <button className="link-button" onClick={() => location.reload()}>reload the page</button>.
              Any reservation you made is safe.
            </p>
          </div>
        </main>
      )
    }
    return this.props.children
  }
}
