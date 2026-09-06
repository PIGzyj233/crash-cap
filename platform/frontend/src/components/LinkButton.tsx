import { Button,type ButtonProps } from 'antd'
import { useNavigate } from 'react-router-dom'

/** One semantic anchor, with SPA navigation and normal new-tab/keyboard behavior. */
export function LinkButton({ to, onClick, ...props }: Omit<ButtonProps, 'href'> & { to: string }) {
  const navigate = useNavigate()
  return <Button {...props} href={to} onClick={event => {
    onClick?.(event)
    if (!event.defaultPrevented && event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey && !props.target) {
      event.preventDefault(); navigate(to)
    }
  }} />
}
