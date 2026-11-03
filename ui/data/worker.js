import {tableReader} from './query.js';
import {replayBuilder} from './replay.js';

const readers = new Map(), replays = new Map();
self.onmessage = async ({data:{id,table,params,base,checksums,operation='query'}}) => {
  try {
    const key=base+JSON.stringify(table);
    const loadChunk=async number=>{
      const response=await fetch(new URL(table.chunks[number],base));
      if(!response.ok)throw new Error(`Cannot load saved records (${response.status}). Reload to retry.`);
      const bytes=await response.arrayBuffer();
      const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');
      if(hash!==checksums[number])throw new Error('The data snapshot changed. Reload the page to get the current version.');
      return new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).json();
    };
    let result;
    if(operation==='replay'){
      const replayKey=key+JSON.stringify([params.agent || '',checksums]);
      if(!replays.has(replayKey)){
        const builder=replayBuilder(table.columns,params.agent);
        for(let c=0;c<table.chunks.length;c++){
          builder.add(await loadChunk(c));
          self.postMessage({id,progress:`Preparing recorded events: ${Math.round((c+1)/table.chunks.length*100)}%`});
        }
        replays.set(replayKey,builder.finish());
        while(replays.size>2)replays.delete(replays.keys().next().value);
      }
      result=replays.get(replayKey);
    }else{
      if(!readers.has(key))readers.set(key,tableReader(table,loadChunk));
      while(readers.size>2)readers.delete(readers.keys().next().value);
      result=await readers.get(key)(params,message=>self.postMessage({id,progress:message}));
    }
    self.postMessage({id,result});
  }catch(e){self.postMessage({id,error:e.message || String(e)});}
};
