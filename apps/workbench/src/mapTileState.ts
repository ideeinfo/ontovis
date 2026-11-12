/** Keep map failures by source URL while that resource remains visible. */
export function visibleTileFailures(failures:ReadonlySet<string>,visible:ReadonlySet<string>):ReadonlySet<string> {
  const retained=new Set([...failures].filter(url=>visible.has(url)));
  return retained.size===failures.size?failures:retained;
}
export function tileLoadResult(failures:ReadonlySet<string>,visible:ReadonlySet<string>,url:string,loaded:boolean):ReadonlySet<string> {
  if(!visible.has(url)||failures.has(url)!==loaded)return failures;
  const next=new Set(failures);
  if(loaded)next.delete(url);else next.add(url);
  return next;
}
