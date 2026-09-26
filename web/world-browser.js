const $=id=>document.getElementById(id);
const labels={ready:'Ready offline',partial:'Partial import',collected:'Archive collected','not-collected':'Not collected',collecting:'Copying from Xbox',importing:'Importing locally',failed:'Import needs attention',invalid:'Invalid cache'};
let inventory=[],token=null,busy=false,xboxConfigured=false;
const number=n=>Number(n||0).toLocaleString();
const bytes=n=>n>=1024**3?(n/1024**3).toFixed(2)+' GB':(n/1024**2).toFixed(1)+' MB';
function el(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;}
function render(){
  const expanded=new Set([...$('worldCards').querySelectorAll('article[data-world]')].filter(c=>c.querySelector('details')?.open).map(c=>c.dataset.world));
  const preparing=inventory.some(w=>['collecting','importing'].includes(w.status));
  const query=$('worldSearch').value.trim().toLowerCase(),filter=$('worldFilter').value;
  const items=inventory.filter(w=>(w.name+' '+w.kind).toLowerCase().includes(query)&&(filter==='all'||filter==='local'&&(w.collected||w.canOpen)||filter==='ready'&&w.canOpen));
  $('worldCards').replaceChildren();
  for(const w of items){
    const card=el('article',null,'worldCard '+w.status),top=el('div',null,'cardTop');
    card.dataset.world=w.id;
    top.append(el('span',w.kind.toUpperCase(),'eyebrow'),el('span',labels[w.status]??w.status,'worldState'));card.append(top,el('h2',w.name),el('p',w.detail,'description'));
    const stats=el('div',null,'worldMetrics');
    if(w.canOpen){for(const [v,k] of [[w.sectionCount,'world sections'],[w.summary.triangles,'render triangles'],[w.summary.textures,'decoded textures']]){const d=el('div');d.append(el('strong',number(v)),el('span',k));stats.append(d);}}
    else if(w.status==='collecting')stats.append(el('strong',bytes(w.receivedBytes||0)+(w.expectedBytes?' / '+bytes(w.expectedBytes):' copied')));
    else stats.append(el('strong',w.collected?bytes(w.archiveBytes)+' on disk':'Available from game files'));
    card.append(stats);
    if(w.canOpen){
      const a=el('a',w.status==='ready'?'Open world →':'Inspect partial world →','openWorld');a.href='/level.html?world='+encodeURIComponent(w.id);card.append(a);
      if(w.id==='blackbox'){const generator=el('a','Generate park layout →','openWorld');generator.href='/park.html';card.append(generator);}
      if(w.bounds)card.append(el('small',`${Math.round(w.bounds[1][0]-w.bounds[0][0])} × ${Math.round(w.bounds[1][2]-w.bounds[0][2])} m · original world coordinates`));
    }else if(['collecting','importing'].includes(w.status)){
      const p=el('progress'),total=w.status==='collecting'?w.expectedBytes:w.job?.total;p.max=total||1;if(total)p.value=w.status==='collecting'?(w.receivedBytes||0):(w.job?.current||0);p.setAttribute('aria-label',w.name+' preparation progress');card.append(p,el('span','Preparing local world…','unavailable'));
    }else if(w.kind!=='overlay'){
      const local=w.collected||w.availableOnDrive;const b=el('button',local?'Import local archive':xboxConfigured?'Collect from Xbox':'Choose game folder','prepareWorld');b.disabled=busy||preparing;b.title=preparing?'Another world is being prepared.':local?'Copy if needed, then decode this archive locally.':xboxConfigured?'Read this archive from your configured Xbox, then decode it locally.':'Choose your extracted game folder above.';b.onclick=()=>local||xboxConfigured?prepare(w):$('gameFolder').focus();card.append(b);
    }else card.append(el('span','Requires the University base world','unavailable'));
    if(w.issues.length){const d=el('details'),s=el('summary',`${w.issues.length} unsupported resource components`);d.open=expanded.has(w.id);d.append(s);const reasons=new Map();for(const i of w.issues){const k=i.component+': '+i.reason;reasons.set(k,(reasons.get(k)||0)+1);}for(const [r,n] of reasons)d.append(el('p',`${n} × ${r}`));card.append(d);}
    card.append(el('code',w.archive));$('worldCards').append(card);
  }
  $('emptyWorlds').hidden=!!items.length;
  const count=inventory.filter(w=>w.canOpen).length;$('worldCount').textContent=`${count} ${count===1?'world':'worlds'} can open locally · ${inventory.filter(w=>w.collected).length} archives collected`;
}
async function prepare(world){
  busy=true;render();$('browserStatus').textContent=world.collected?'Starting local import…':'Starting read-only archive collection from Xbox…';
  try{
    if(!token){const r=await fetch('/api/bootstrap');if(!r.ok)throw Error('The local service is unavailable.');token=(await r.json()).token;}
    const r=await fetch('/api/worlds/prepare',{method:'POST',headers:{'Content-Type':'application/json','X-NativeX-Token':token},body:JSON.stringify({id:world.id})}),value=await r.json();
    if(!r.ok)throw Error(value.error||'Could not start world preparation.');await refresh();
  }catch(e){$('browserStatus').textContent=e.message;}
  finally{busy=false;render();}
}
async function refresh(){
  try{const r=await fetch('/api/worlds');if(!r.ok)throw Error('World browser needs the updated level service. Open the “Launch NativeX Level Editor” launcher.');const data=await r.json();inventory=data.worlds;xboxConfigured=!!data.xboxConfigured;$('sourceFolder').textContent=data.sourceDirectory;$('browserStatus').textContent='Cached worlds open without an Xbox connection.';render();}
  catch(e){$('browserStatus').textContent=e.message;}
}
$('refreshWorlds').onclick=refresh;$('worldSearch').oninput=render;$('worldFilter').onchange=render;
await refresh();setInterval(()=>{if(!document.hidden&&inventory.some(w=>['collecting','importing'].includes(w.status)))refresh();},5000);

async function loadSetup(){
  const response=await fetch('/api/library');const value=await response.json();
  if(value.gameContent)$('gameFolder').value=value.gameContent;
  $('setupStatus').textContent=value.mounted?`${value.worlds.length} supported archives found. Choose Import local archive below.`:value.gameContent?'The saved game folder is disconnected. Reconnect the drive or choose another folder.':'No game folder connected. Browsing cached worlds stays offline.';
}
$('gameFolderForm').onsubmit=async event=>{
  event.preventDefault();$('connectFolder').disabled=true;
  try{
    if(!token)token=(await (await fetch('/api/bootstrap')).json()).token;
    const response=await fetch('/api/library/configure',{method:'POST',headers:{'Content-Type':'application/json','X-NativeX-Token':token},body:JSON.stringify({path:$('gameFolder').value})});
    const value=await response.json();if(!response.ok)throw Error(value.error||'Could not open this folder.');
    await loadSetup();await refresh();
  }catch(error){$('setupStatus').textContent=error.message;}
  finally{$('connectFolder').disabled=false;}
};
await loadSetup();
