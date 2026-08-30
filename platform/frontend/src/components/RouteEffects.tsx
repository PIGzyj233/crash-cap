import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'

export function RouteEffects() {
  const location = useLocation()
  useEffect(() => {
    let observer: MutationObserver | undefined
    let timeout: number | undefined
    const focusHeading = () => {
      const heading = document.querySelector<HTMLElement>('h1')
      if (!heading) return false
      heading.focus({ preventScroll: true })
      document.title = `${heading.textContent?.trim() || 'Crash-Cap'} · Crash-Cap`
      observer?.disconnect()
      if (timeout !== undefined) window.clearTimeout(timeout)
      return true
    }
    document.title = 'Crash-Cap'
    const frame = window.requestAnimationFrame(() => {
      if (focusHeading()) return
      observer = new MutationObserver(() => focusHeading())
      observer.observe(document.getElementById('root') ?? document.body, { childList: true, subtree: true })
      timeout = window.setTimeout(() => observer?.disconnect(), 5_000)
    })
    return () => {
      window.cancelAnimationFrame(frame)
      observer?.disconnect()
      if (timeout !== undefined) window.clearTimeout(timeout)
    }
  }, [location.pathname])
  return null
}
