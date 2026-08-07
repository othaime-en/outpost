import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.tsx'

// Self-hosted variable fonts (via @fontsource) — no external Google Fonts
// request, so this works offline and inside Docker without a CDN
// dependency.
import '@fontsource-variable/inter'
import '@fontsource-variable/geist'
import '@fontsource-variable/geist-mono'

import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
    <React.StrictMode>
        <App />
    </React.StrictMode>,
)