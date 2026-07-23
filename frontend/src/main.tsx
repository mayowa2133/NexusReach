import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './lib/observability'
import { Sentry } from './lib/observability'
import './index.css'
import App from './App.tsx'
import { installDemoNavigationGuard } from './lib/demoMode'

installDemoNavigationGuard()

createRoot(document.getElementById('root')!, {
  onUncaughtError: Sentry.reactErrorHandler(),
  onCaughtError: Sentry.reactErrorHandler(),
  onRecoverableError: Sentry.reactErrorHandler(),
}).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
