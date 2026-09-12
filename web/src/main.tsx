import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { RouterProvider } from 'react-router-dom'
import { AppVersionGuard } from './components/AppVersionGuard'
import { AuthProvider } from './context/AuthContext'
import { router } from './router'
import './styles/global.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppVersionGuard />
    <AuthProvider>
      <RouterProvider router={router} />
    </AuthProvider>
  </StrictMode>,
)
