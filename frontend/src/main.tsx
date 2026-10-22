import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import '@fontsource/lora/600.css'
import '@fontsource/lora/700.css'
import App from './App.tsx'
import DialogHost from './components/DialogHost'
import { I18nProvider } from './i18n.tsx'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <I18nProvider>
      <BrowserRouter>
        <App />
        <DialogHost />
      </BrowserRouter>
    </I18nProvider>
  </StrictMode>,
)
