const implementedPages=['project','models','bindings','hierarchy','scene','orders','analysis','data','ai'] as const;
export type WorkbenchPage=typeof implementedPages[number];

export function isGlobalPage(page:WorkbenchPage){return page==='project'||page==='models';}

export function canNavigate(page:string,hasProject:boolean):page is WorkbenchPage{
  return implementedPages.some(value=>value===page)&&(page==='project'||page==='models'||hasProject);
}

export function workbenchHeader(page:WorkbenchPage,moduleName:string,projectName:string){
  return isGlobalPage(page)||!projectName?moduleName:`${moduleName} - ${projectName}`;
}
