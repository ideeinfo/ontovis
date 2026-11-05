import {Fragment,useRef,type ReactElement,type ReactNode} from 'react';
import * as Dropdown from '@radix-ui/react-dropdown-menu';
import * as Context from '@radix-ui/react-context-menu';
import {MoreHorizontal} from 'lucide-react';

export interface ListAction {
  id:string;label:string;icon:ReactNode;onSelect:()=>void;disabled?:boolean;danger?:boolean;separatorBefore?:boolean;opensDialog?:boolean;
}

function ActionItems({actions,context=false,onSelect}:{actions:readonly ListAction[];context?:boolean;onSelect:(action:ListAction)=>void}) {
  const Item=context?Context.Item:Dropdown.Item,Separator=context?Context.Separator:Dropdown.Separator;
  return <>{actions.map((action,index)=><Fragment key={action.id}>
    {index>0&&(action.separatorBefore||action.danger&&!actions[index-1].danger)&&<Separator className="ov-list-menu-separator"/>}
    <Item className={`ov-list-menu-item${action.danger?' danger':''}`} disabled={action.disabled}
      onSelect={()=>{if(!action.disabled)onSelect(action);}}>{action.icon}<span>{action.label}</span></Item>
  </Fragment>)}</>;
}

function useMenuSelection(){
  const dialogAction=useRef<(()=>void)|null>(null);
  const select=(action:ListAction)=>{if(action.opensDialog)dialogAction.current=action.onSelect;else action.onSelect();};
  const afterClose=()=>{
    const action=dialogAction.current;dialogAction.current=null;
    // Finish the menu's focus-scope teardown before a dialog claims focus.
    if(action)queueMicrotask(action);
  };
  return {select,afterClose};
}

export function RowActions({name,actions,locale='zh',disabled=false}:{name:string;actions:readonly ListAction[];locale?:string;disabled?:boolean}) {
  const {select,afterClose}=useMenuSelection();
  return <Dropdown.Root><Dropdown.Trigger asChild>
    <button type="button" className="ov-row-more" disabled={disabled} aria-label={`${locale==='en'?'More actions for':'更多操作：'} ${name}`}
      onClick={event=>event.stopPropagation()}><MoreHorizontal size={16} aria-hidden="true"/></button>
  </Dropdown.Trigger><Dropdown.Portal><Dropdown.Content className="ov-list-menu" align="end" sideOffset={4} collisionPadding={8}
    onClick={event=>event.stopPropagation()} onContextMenu={event=>event.preventDefault()}
    onCloseAutoFocus={afterClose}>
    <Dropdown.Label className="ov-list-menu-caption">{name}</Dropdown.Label>
    <ActionItems actions={actions} onSelect={select}/>
  </Dropdown.Content></Dropdown.Portal></Dropdown.Root>;
}

export function RowContext({name,actions,children,disabled=false}:{name:string;actions:readonly ListAction[];children:ReactElement;disabled?:boolean}) {
  const {select,afterClose}=useMenuSelection();
  return <Context.Root><Context.Trigger asChild disabled={disabled}>{children}</Context.Trigger>
    <Context.Portal><Context.Content className="ov-list-menu" collisionPadding={8} onClick={event=>event.stopPropagation()}
      onCloseAutoFocus={afterClose}>
      <Context.Label className="ov-list-menu-caption">{name}</Context.Label><ActionItems context actions={actions} onSelect={select}/>
    </Context.Content></Context.Portal>
  </Context.Root>;
}
