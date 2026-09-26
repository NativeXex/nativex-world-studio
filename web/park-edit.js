// Pure editing helpers shared by the viewport and regression tests.
export function snapDelta(values){
 if(!Array.isArray(values)||values.length!==3||!values.every(v=>typeof v==='number'&&Number.isFinite(v)))throw Error('Use finite X and Z positions.');
 return [Math.round(values[0]*2)/2,0,Math.round(values[2]*2)/2];
}
export function proposeMove(plan,id,delta){
 const next=structuredClone(plan),item=next.modules.find(m=>m.id===id);
 if(!item)throw Error('Select one of the verified movable groups.');
 if(item.locked)throw Error('Unlock this group before moving it.');
 item.delta=snapDelta(delta);return next;
}
export function identifyHit(hit,lookup,ceiling=6){
 if(!hit||hit.point.y>ceiling||!Number.isInteger(hit.faceIndex)||hit.faceIndex<0)return null;
 const source=hit.object.userData.source;
 if(!source||hit.faceIndex>=source.triangles.length)return null;
 const triangle=source.triangles[hit.faceIndex];
 const id=lookup?.[source.asset]?.[String(source.section)]?.[triangle];
 return typeof id==='string'?{id,asset:source.asset,section:source.section,triangle}:null;
}
