import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

console.log('main.tsx: starting render');
const rootElement = document.getElementById('root');
if (!rootElement) {
  console.error('root element not found');
} else {
  createRoot(rootElement).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
  console.log('main.tsx: render called');
}
