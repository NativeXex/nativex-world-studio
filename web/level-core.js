// Level plans reference immutable native world sections, never park recipes.
export const copy = x => structuredClone(x);
export const MAX_LEVEL_SECTIONS = 2048;
export function newLevel(source) {
  return {format:'nativex-level-plan',version:1,id:crypto.randomUUID(),name:source.name+' — edit',
    sourceId:source.id,sourceSha256:source.sourceSha256,gameBuild:source.gameBuild,
    instances:source.sections.map(s=>({id:crypto.randomUUID(),sectionId:s.id,position:[...s.pivot],yaw:0,locked:false,visible:true,origin:'original'})),
    seed:'37',generationHistory:[]};
}
export function transformPoint(v,o,s) {
  const a=o.yaw*Math.PI/180,c=Math.cos(a),t=Math.sin(a),x=v[0]-s.pivot[0],z=v[2]-s.pivot[2];
  return [o.position[0]+c*x+t*z,o.position[1]+v[1]-s.pivot[1],o.position[2]-t*x+c*z];
}
export function isOriginalArrangement(p,source) {
  if(p.instances.length!==source.sections.length)return false;
  return source.sections.every(s=>{
    const matches=p.instances.filter(o=>o.sectionId===s.id);
    return matches.length===1&&matches[0].origin==='original'&&matches[0].visible&&matches[0].yaw%360===0&&matches[0].position.every((v,i)=>Math.abs(v-s.pivot[i])<1e-6);
  });
}
export function sectionBounds(o,s) {
  // Use both render and collision bounds, including collision-only extents.
  const boxes=[s.bounds,...s.collision.map(c=>c.bounds)],min=[0,1,2].map(i=>Math.min(...boxes.map(b=>b[0][i]))),max=[0,1,2].map(i=>Math.max(...boxes.map(b=>b[1][i])));
  const points=[];
  for(const x of [min[0],max[0]])for(const y of [min[1],max[1]])for(const z of [min[2],max[2]])points.push(transformPoint([x,y,z],o,s));
  return {min:[0,1,2].map(i=>Math.min(...points.map(p=>p[i]))),max:[0,1,2].map(i=>Math.max(...points.map(p=>p[i])))};
}
export function validateLevel(p,source) {
  const errors=[];
  if(p?.format!=='nativex-level-plan'||p.version!==1||p.sourceId!==source.id||p.sourceSha256!==source.sourceSha256||p.gameBuild!==source.gameBuild)errors.push('Level source or format does not match the collected archive.');
  if(!Array.isArray(p?.instances)||p.instances.length>MAX_LEVEL_SECTIONS)return {errors:[...errors,'Invalid section count.']};
  const ids=new Set(),sections=new Map(source.sections.map(s=>[s.id,s]));
  for(const o of p.instances){
    if(typeof o.id!=='string'||ids.has(o.id))errors.push('Duplicate or missing section identity.');ids.add(o.id);
    if(!sections.has(o.sectionId))errors.push('Unknown native world section.');
    if(!Array.isArray(o.position)||o.position.length!==3||!o.position.every(v=>typeof v==='number'&&Number.isFinite(v)&&Math.abs(v)<100000))errors.push('Invalid section position.');
    if(!Number.isFinite(o.yaw)||o.yaw%15!==0)errors.push('Section rotation must use 15° steps.');
    if(typeof o.locked!=='boolean'||typeof o.visible!=='boolean'||!['original','copy'].includes(o.origin))errors.push('Invalid section state.');
  }
  return {errors:[...new Set(errors)],warnings:['Section edges, AI routes, triggers, streaming and spawn data require a native rebuild before Xbox export.']};
}
function random(seed){let h=2166136261;for(const c of String(seed))h=Math.imul(h^c.charCodeAt(0),16777619);return()=>{h+=0x6D2B79F5;let t=h;t=Math.imul(t^t>>>15,t|1);t^=t+Math.imul(t^t>>>7,t|61);return((t^t>>>14)>>>0)/4294967296;};}
export function generateLevel(p,source,seed,gap=2) {
  const validation=validateLevel(p,source);if(validation.errors.length)throw Error(validation.errors.join(' '));
  if(!Number.isFinite(gap)||gap<1||gap>30)throw Error('Section spacing must be between 1 and 30 metres.');
  const next=copy(p),movable=next.instances.filter(o=>!o.locked&&o.visible),locked=next.instances.filter(o=>o.locked&&o.visible),rng=random(seed),lookup=new Map(source.sections.map(s=>[s.id,s]));
  if(!movable.length)throw Error('Unlock at least one visible world section.');
  for(let i=movable.length-1;i>0;i--){const j=Math.floor(rng()*(i+1));[movable[i],movable[j]]=[movable[j],movable[i]];}
  const widths=movable.map(o=>{const b=sectionBounds({...o,position:[0,0,0],yaw:0},lookup.get(o.sectionId));return Math.max(b.max[0]-b.min[0],b.max[2]-b.min[2]);}),step=Math.max(...widths)+gap,cols=Math.ceil(Math.sqrt(movable.length));
  const origin=[(source.bounds[0][0]+source.bounds[1][0])/2,(source.bounds[0][2]+source.bounds[1][2])/2];
  const occupied=locked.map(o=>sectionBounds(o,lookup.get(o.sectionId)));
  let slot=0;
  for(const o of movable){
    o.yaw=Math.floor(rng()*4)*90;const s=lookup.get(o.sectionId);let placed=false;
    for(let tries=0;tries<500;tries++,slot++){
      o.position=[origin[0]+(slot%cols-(cols-1)/2)*step,0,origin[1]+(Math.floor(slot/cols)-(cols-1)/2)*step];
      const b=sectionBounds(o,s);
      if(!occupied.some(a=>a.min[0]<b.max[0]+gap&&a.max[0]+gap>b.min[0]&&a.min[2]<b.max[2]+gap&&a.max[2]+gap>b.min[2])){occupied.push(b);slot++;placed=true;break;}
    }
    if(!placed)throw Error('No clear section placement found.');
  }
  next.seed=String(seed);
  const plan={kind:'section-layout-study',seed:String(seed),gap,sections:movable.length,
    note:'Reuses complete world sections with their textures, collision and grinds. Spaces between sections are deliberate; connectors are not generated. Xbox export is not supported.'};
  next.generationHistory.push(plan);
  return {project:next,plan,base:JSON.stringify(p)};
}
