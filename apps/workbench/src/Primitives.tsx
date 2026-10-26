import type { ReactNode, ButtonHTMLAttributes } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { usePreferences } from './Preferences';

export function Badge({children, tone = 'neutral'}: {children: ReactNode; tone?: string}) {
  return <span className={`ov-badge ${tone}`}>{children}</span>;
}
export function Btn({children, primary, className='', ...props}: ButtonHTMLAttributes<HTMLButtonElement> & {primary?: boolean}) {
  return <button type="button" {...props} className={`ov-btn ${primary ? 'primary' : ''} ${className}`}>{children}</button>;
}
export function IconBtn({label, children, ...props}: ButtonHTMLAttributes<HTMLButtonElement> & {label: string}) {
  return <button type="button" {...props} className="ov-icon-btn" aria-label={label} title={label}>{children}</button>;
}
export function Panel({title, children, className = ''}: {title?: ReactNode; children: ReactNode; className?: string}) {
  return <section className={`ov-panel ${className}`}>{title && <div className="ov-panel-head"><h2>{title}</h2></div>}{children}</section>;
}
export function Modal({title, description, onClose, children, onCloseAutoFocus, className=''}: {title: string; description: string; onClose: () => void; children: ReactNode; onCloseAutoFocus?:(event:Event)=>void;className?:string}) {
  const {t} = usePreferences();
  return <Dialog.Root open onOpenChange={open => {if (!open) onClose();}}><Dialog.Portal>
    <div className="ov-app ov-modal-root"><Dialog.Overlay className="ov-modal-overlay" />
      <Dialog.Content className={`ov-dialog${className?' '+className:''}`} aria-describedby="ov-dialog-description" onCloseAutoFocus={onCloseAutoFocus}>
        <header><Dialog.Title>{title}</Dialog.Title><Dialog.Close asChild><IconBtn label={t('close')}><X size={18} /></IconBtn></Dialog.Close></header>
        <Dialog.Description id="ov-dialog-description" className="ov-sr-only">{description}</Dialog.Description>
        <div className="ov-dialog-body">{children}</div>
      </Dialog.Content></div>
  </Dialog.Portal></Dialog.Root>;
}
