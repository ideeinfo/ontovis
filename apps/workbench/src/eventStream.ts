export interface ServerEvent {event:string;id:string;data:string}
export class StreamReadError extends Error {}

/** The stream is bounded by this product's three-minute journal. */
export class EventStreamDecoder {
  private encoder=new TextEncoder();
  private pending='';
  private data:string[]=[];
  private type='message';
  private id='';
  private skipLF=false;
  private beginning=true;
  private bytes=0;
  private count=0;
  push(text:string):ServerEvent[]{
    if(this.beginning&&text){this.beginning=false;if(text[0]==='\uFEFF')text=text.slice(1);}
    if(this.skipLF&&text){if(text[0]==='\n')text=text.slice(1);this.skipLF=false;}
    this.pending+=text;
    if(this.pending.length>1048576)throw new StreamReadError('STREAM_PROTOCOL_INVALID');
    const result:ServerEvent[]=[];
    let at=0,match:RegExpExecArray|null;
    const newline=/\r\n|\r|\n/g;
    while((match=newline.exec(this.pending))){
      const line=this.pending.slice(at,match.index);at=newline.lastIndex;
      if(match[0]==='\r'&&at===this.pending.length)this.skipLF=true;
      this.bytes+=this.encoder.encode(line).byteLength+1;
      if(this.bytes>262144)throw new StreamReadError('STREAM_PROTOCOL_INVALID');
      if(line===''){
        if(this.data.length){
          if(++this.count>400)throw new StreamReadError('STREAM_PROTOCOL_INVALID');
          result.push({event:this.type,id:this.id,data:this.data.join('\n')});
        }
        this.data=[];this.type='message';this.bytes=0;
      }else if(line[0]!==':'){
        const split=line.indexOf(':'),field=split<0?line:line.slice(0,split);
        let value=split<0?'':line.slice(split+1);if(value.startsWith(' '))value=value.slice(1);
        if(field==='data')this.data.push(value);
        else if(field==='event')this.type=value||'message';
        else if(field==='id'&&!value.includes('\0'))this.id=value;
      }
    }
    this.pending=this.pending.slice(at);
    if(this.encoder.encode(this.pending).byteLength+this.bytes>262144)throw new StreamReadError('STREAM_PROTOCOL_INVALID');
    return result;
  }
}

export async function readServerEvents(body:ReadableStream<Uint8Array>,onEvent:(event:ServerEvent)=>void,guard:()=>void,timeoutMs=10000){
  const reader=body.getReader(),decoder=new TextDecoder('utf-8',{fatal:true}),parser=new EventStreamDecoder();
  let total=0;
  try{
    while(true){
      let timer:ReturnType<typeof setTimeout>|undefined;
      const next=await Promise.race([reader.read(),new Promise<never>((_,reject)=>{
        timer=setTimeout(()=>reject(new StreamReadError('STREAM_STALLED')),timeoutMs);
      })]).finally(()=>clearTimeout(timer));
      guard();
      if(next.done){parser.push(decoder.decode()).forEach(onEvent);return;}
      total+=next.value.byteLength;
      if(total>1048576)throw new StreamReadError('STREAM_PROTOCOL_INVALID');
      for(const frame of parser.push(decoder.decode(next.value,{stream:true}))){guard();onEvent(frame);}
    }
  }finally{
    await reader.cancel().catch(()=>{});reader.releaseLock();
  }
}
