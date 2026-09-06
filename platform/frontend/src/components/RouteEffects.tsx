import { useEffect } from 'react'
import { useLocation } from 'react-router-dom'

export function RouteEffects() {
  const location = useLocation()
  useEffect(() => {
    const previous = window.history.scrollRestoration
    window.history.scrollRestoration = 'manual'
    return () => { window.history.scrollRestoration = previous }
  }, [])
  useEffect(() => {
    const list = /\/(occurrences|symbols|artifacts)$/.test(location.pathname)
    if (!list) { window.scrollTo(0, 0); return }
    const key = `crashcap.scroll:${location.pathname}${location.search}`
    let target = 0
    try { target = Number(sessionStorage.getItem(key)) || 0 } catch { /* Storage is optional. */ }
    let restored = false
    let lastKnownY = target
    const persist = () => { if (restored) { try { sessionStorage.setItem(key, String(lastKnownY)) } catch { /* Storage is optional. */ } } }
    const save = () => { if (restored) { lastKnownY = window.scrollY; persist() } }
    const restore = () => {
      window.scrollTo(0, target)
      if (document.documentElement.scrollHeight - window.innerHeight >= target) { restored = true; observer.disconnect() }
    }
    const observer = new MutationObserver(restore)
    observer.observe(document.getElementById('root') ?? document.body, { subtree: true, childList: true })
    const frame = window.requestAnimationFrame(restore)
    const timeout = window.setTimeout(() => { restored = true; observer.disconnect() }, 5000)
    window.addEventListener('scroll', save, { passive: true })
    return () => { persist(); observer.disconnect(); window.cancelAnimationFrame(frame); window.clearTimeout(timeout); window.removeEventListener('scroll', save) }
  }, [location.pathname, location.search])
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
