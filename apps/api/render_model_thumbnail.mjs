/** One bounded, private render. Chrome receives no user session or credentials. */
import {spawn} from 'node:child_process';
import {createServer} from 'node:http';
import {randomBytes} from 'node:crypto';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {join} from 'node:path';

const [input,output,rendererPath,browser,work]=process.argv.slice(2);
const MAX_PNG=384*1024,MAX_MODEL=20*1024*1024;
let chrome,server,sequence=0,pending=new Map(),buffer=Buffer.alloc(0);
function fail(code){throw new Error(code);}
function send(method,params={},sessionId) {
  return new Promise((resolve,reject)=>{
    const id=++sequence,timer=setTimeout(()=>{pending.delete(id);reject(new Error('THUMBNAIL_TIMEOUT'));},12000);
    pending.set(id,{resolve,reject,timer});
    chrome.stdio[3].write(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})})+'\0');
  });
}
async function main() {
  const [model,renderer]=await Promise.all([readFile(input),readFile(rendererPath)]);
  if(model.length<24||model.length>MAX_MODEL||renderer.length>2*1024*1024)fail('THUMBNAIL_SOURCE_INVALID');
  const token=randomBytes(24).toString('hex'),prefix='/'+token+'/';
  const html=Buffer.from('<!doctype html><meta charset="utf-8"><title>ONTOVis model thumbnail</title><script src="'+prefix+'renderer.js"></script>');
  server=createServer((req,res)=>{
    const resource=req.method==='GET'&&req.url===prefix?[html,'text/html']:
      req.method==='GET'&&req.url===prefix+'renderer.js'?[renderer,'text/javascript']:
      req.method==='GET'&&req.url===prefix+'model.glb'?[model,'model/gltf-binary']:null;
    if(!resource){res.writeHead(404).end();return;}
    res.writeHead(200,{'Content-Type':resource[1],'Content-Length':resource[0].length,'Cache-Control':'no-store',
      'Content-Security-Policy':"default-src 'none'; script-src 'self'; connect-src 'self' blob:; img-src blob: data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"});
    res.end(resource[0]);
  });
  await new Promise((resolve,reject)=>{server.on('error',reject);server.listen(0,'127.0.0.1',resolve);});
  await mkdir(join(work,'chrome'),{mode:0o700});
  chrome=spawn(browser,['--headless=new','--no-sandbox','--disable-background-networking','--disable-extensions',
    '--disable-component-update','--disable-sync','--no-first-run','--no-default-browser-check','--disable-dev-shm-usage',
    '--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader','--num-raster-threads=1',
    '--renderer-process-limit=1','--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1',
    '--remote-debugging-pipe','--user-data-dir='+join(work,'chrome'),'about:blank'],
    {stdio:['ignore','ignore','ignore','pipe','pipe'],env:{...process.env,XDG_CONFIG_HOME:work,XDG_CACHE_HOME:work}});
  chrome.on('error',()=>{for(const p of pending.values()){clearTimeout(p.timer);p.reject(new Error('THUMBNAIL_BROWSER_UNAVAILABLE'));}pending.clear();});
  chrome.on('exit',()=>{for(const p of pending.values()){clearTimeout(p.timer);p.reject(new Error('THUMBNAIL_BROWSER_UNAVAILABLE'));}pending.clear();});
  chrome.stdio[4].on('data',chunk=>{
    buffer=Buffer.concat([buffer,chunk]);if(buffer.length>2*1024*1024){chrome.kill('SIGKILL');return;}
    let end;while((end=buffer.indexOf(0))!==-1){
      const raw=buffer.subarray(0,end);buffer=buffer.subarray(end+1);
      try {const message=JSON.parse(raw.toString());if(!message.id)continue;const item=pending.get(message.id);if(!item)continue;
        pending.delete(message.id);clearTimeout(item.timer);message.error?item.reject(new Error('THUMBNAIL_BROWSER_FAILED')):item.resolve(message.result);
      }catch{chrome.kill('SIGKILL');}
    }
  });
  const {targetId}=await send('Target.createTarget',{url:'about:blank'});
  const {sessionId}=await send('Target.attachToTarget',{targetId,flatten:true});
  await send('Page.enable',{},sessionId);await send('Runtime.enable',{},sessionId);
  await send('Page.navigate',{url:'http://127.0.0.1:'+server.address().port+prefix},sessionId);
  let ready=false;
  for(let i=0;i<100;i++){
    const value=await send('Runtime.evaluate',{expression:'typeof window.ontoVisThumbnail',returnByValue:true},sessionId);
    if(value.result?.value==='function'){ready=true;break;}await new Promise(resolve=>setTimeout(resolve,50));
  }
  if(!ready)fail('THUMBNAIL_BROWSER_FAILED');
  const value=await send('Runtime.evaluate',{expression:'window.ontoVisThumbnail()',awaitPromise:true,returnByValue:true},sessionId);
  if(value.exceptionDetails||!value.result?.value)fail('THUMBNAIL_RENDER_FAILED');
  const result=value.result.value,png=Buffer.from(result.png,'base64');
  if(png.length>MAX_PNG||result.width!==256||result.height!==256||result.coveredPixels<16)fail('THUMBNAIL_EMPTY_RENDER');
  await writeFile(output,png,{mode:0o600,flag:'wx'});
  console.log(JSON.stringify({state:'ready',bytes:png.length,width:256,height:256,coveredPixels:result.coveredPixels}));
}
try {await main();}catch(error){
  const code=/^THUMBNAIL_[A-Z_]+$/.test(error.message)?error.message:'THUMBNAIL_RENDER_FAILED';
  console.log(JSON.stringify({state:'failed',code}));process.exitCode=2;
}finally{
  for(const p of pending.values()){clearTimeout(p.timer);p.reject(new Error('THUMBNAIL_INTERRUPTED'));}pending.clear();
  if(chrome&&chrome.exitCode===null){
    const ended=new Promise(resolve=>chrome.once('exit',resolve));chrome.kill('SIGTERM');
    await Promise.race([ended,new Promise(resolve=>setTimeout(resolve,1000))]);
    if(chrome.exitCode===null)chrome.kill('SIGKILL');
  }
  if(server){server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
}
