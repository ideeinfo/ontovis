import { useId, useRef, type ReactNode, type ButtonHTMLAttributes } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { TriangleAlert, X } from 'lucide-react';
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
type ModalProps = {
  title:string; description:string; onClose:()=>void; children:ReactNode; className?:string;
  closeDisabled?:boolean; onOpenAutoFocus?:(event:Event)=>void; onCloseAutoFocus?:(event:Event)=>void;
};
export function Modal({title, description, onClose, children, closeDisabled, onOpenAutoFocus, onCloseAutoFocus, className=''}:ModalProps) {
  const {t} = usePreferences();
  const descriptionId = useId();
  return <Dialog.Root open onOpenChange={open => {if (!open && !closeDisabled) onClose();}}><Dialog.Portal>
    <div className="ov-app ov-modal-root"><Dialog.Overlay className="ov-modal-overlay" />
      <Dialog.Content className={`ov-dialog${className?' '+className:''}`} aria-describedby={descriptionId} onOpenAutoFocus={onOpenAutoFocus} onCloseAutoFocus={onCloseAutoFocus}>
        <header><Dialog.Title>{title}</Dialog.Title><Dialog.Close asChild><IconBtn label={t('close')} disabled={closeDisabled}><X size={18} /></IconBtn></Dialog.Close></header>
        <Dialog.Description id={descriptionId} className="ov-sr-only">{description}</Dialog.Description>
        <div className="ov-dialog-body">{children}</div>
      </Dialog.Content></div>
  </Dialog.Portal></Dialog.Root>;
}

type ConfirmationDialogProps = Pick<ModalProps,'title'|'description'|'onClose'|'closeDisabled'|'children'> & {
  subject?:string;
  warning?:string;
  status?:ReactNode;
  cancelLabel?:string;
};
export function ConfirmationDialog({title,subject,description,warning,status,onClose,closeDisabled,cancelLabel,children}:ConfirmationDialogProps) {
  const {locale}=usePreferences();
  const cancel=useRef<HTMLButtonElement>(null);
  return <Modal className="ov-confirm-dialog" title={title}
    description={[subject,description,warning].filter(Boolean).join(' ')} onClose={onClose} closeDisabled={closeDisabled}
    onOpenAutoFocus={event=>{
      if(!cancel.current||cancel.current.disabled)return;
      event.preventDefault();
      cancel.current.focus({preventScroll:true});
    }}>
    <div className="ov-confirm-content">
      {subject&&<p className="ov-confirm-subject">{subject}</p>}
      <p>{description}</p>
      {warning&&<div className="ov-confirm-warning"><TriangleAlert size={16} aria-hidden="true"/><p>{warning}</p></div>}
      {status&&<div className="ov-confirm-status">{status}</div>}
    </div>
    <footer className="ov-confirm-actions">
      <button ref={cancel} className="ov-btn" type="button" disabled={closeDisabled}
        onClick={onClose}>{cancelLabel??(locale==='zh'?'取消':'Cancel')}</button>
      {children}
    </footer>
  </Modal>;
}
