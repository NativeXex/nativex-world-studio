import * as THREE from 'three';
import {OrbitControls} from './vendor/OrbitControls.js';
import {TransformControls} from './vendor/TransformControls.js';
import {proposeMove,identifyHit} from './park-edit.js';

const $=id=>document.getElementById(id),copy=x=>structuredClone(x),status=(s,error=false)=>{$('status').textContent=s;$('status').classList.toggle('error',error);};
let token,catalog,manifest,plan,candidate=null,original=false,busy=true,history=[],at=0,dirty=false;
let selection=null,mode='select',drag=null,manualDraft=null,moveRequest=0,lastValidation=null,moveFeedback='Click a surface to inspect it. Select a tested group to move it.';
const roots=new Map(),oldBoxes=[],overlayObjects=[],materials=[],textures=new Map(),pickables=[];
async function get(url){const r=await fetch(url),v=await r.json();if(!r.ok)throw Error(v.error||`Could not load ${url}`);return v;}
async function post(url,body){const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-NativeX-Token':token},body:JSON.stringify(body)}),v=await r.json();if(!r.ok){const e=Error(v.error||'Local operation failed');e.details=v.details;throw e;}return v;}
function on(id,fn){$(id).onclick=async()=>{if(busy||drag)return;busy=true;sync();try{await fn();}catch(e){status(e.message,true);}finally{busy=false;sync();}};}
function shown(){return original?catalog.original:manualDraft??candidate??plan;}
function commit(next){plan=copy(next);candidate=null;original=false;history=history.slice(0,at+1);history.push(copy(plan));if(history.length>80)history.shift();at=history.length-1;dirty=true;$('exportResult').hidden=true;}
function sync(){
 if(!catalog||!plan)return;
 const current=shown();for(const m of current.modules)roots.get(m.id)?.position.set(...m.delta);
 for(const o of overlayObjects)o.visible=$('collision').checked;
 for(const b of oldBoxes)b.visible=$('footprints').checked&&!original;
 for(const pair of materials)pair.mesh.material=$('lighting').checked?pair.lighting:pair.diffuse;
 $('state').textContent=original?'Original source arrangement':manualDraft?'Move preview · checking':candidate?'Generated candidate · preview':plan.modules.some(m=>m.delta.some(Boolean))?'Accepted layout · local preview':'Original source arrangement';
 $('detail').textContent=$('lighting').checked?'Native baked-light textures · inspection view':'Three obstacle groups · original boundaries · fixed surrounding park';
 $('compare').setAttribute('aria-pressed',String(original));$('compare').textContent=original?'Return to layout':'Compare original';
 $('candidate').hidden=!candidate;$('saved').textContent=dirty?'Unsaved layout':plan.revision?`Saved revision ${plan.revision}`:'Original source';
 for(const id of ['generate','shuffle','open','restore','save','export','keep','discard'])$(id).disabled=busy;
 for(const id of ['save','export','restore','open','generate','shuffle'])$(id).disabled||=!!candidate;
 for(const id of ['compare','selectTool','moveTool'])$(id).disabled=busy||!!drag;
 $('export').disabled||=!plan.modules.some(m=>m.delta.some(Boolean));
 $('undo').disabled=busy||!!candidate||at===0;$('redo').disabled=busy||!!candidate||at===history.length-1;
 $('seed').disabled=busy||!!candidate;
 $('modules').replaceChildren();
 for(const m of current.modules){const definition=catalog.modules.find(v=>v.id===m.id),row=document.createElement('div');row.className='module';
  row.classList.toggle('selected',selection?.id==='module:'+m.id);
  const focus=document.createElement('button'),name=document.createElement('strong'),detail=document.createElement('small');name.textContent=definition.name;detail.textContent=`Δ X ${m.delta[0].toFixed(1)} m · Z ${m.delta[2].toFixed(1)} m`;focus.append(name,detail);focus.onclick=()=>{if(busy||drag)return;select({id:'module:'+m.id});focusModule(m.id);};row.append(focus);
  const label=document.createElement('label'),lock=document.createElement('input');lock.type='checkbox';lock.checked=m.locked;lock.disabled=busy||!!candidate||original;lock.setAttribute('aria-label','Lock '+definition.name);lock.onchange=()=>{const next=copy(plan);next.modules.find(x=>x.id===m.id).locked=lock.checked;commit(next);sync();status(lock.checked?'Group locked for the next generation.':'Group unlocked.');};label.append(lock,'Lock');row.append(label);$('modules').append(row);
 }
 updateInspector();
}
const renderer=new THREE.WebGLRenderer({antialias:true});renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.setClearColor(0x11222c);renderer.localClippingEnabled=true;$('view').append(renderer.domElement);
const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(48,1,.1,1500),controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=true;controls.maxPolarAngle=Math.PI*.49;
scene.add(new THREE.HemisphereLight(0xddebff,0x687483,2.4));const sun=new THREE.DirectionalLight(0xffeddb,2.1);sun.position.set(30,90,45);scene.add(sun);
const clipping=[new THREE.Plane(new THREE.Vector3(0,-1,0),6)],loader=new THREE.TextureLoader();
const raycaster=new THREE.Raycaster(),pointer=new THREE.Vector2(),ground=new THREE.Plane(new THREE.Vector3(0,1,0),0);
const proxy=new THREE.Object3D();scene.add(proxy);
const gizmo=new TransformControls(camera,renderer.domElement);scene.add(gizmo.getHelper());gizmo.setMode('translate');gizmo.setSpace('world');gizmo.showY=false;gizmo.setSize(.85);gizmo.enabled=false;
const selectedBox=new THREE.Box3Helper(new THREE.Box3(),0xffd275);selectedBox.material.depthTest=false;selectedBox.visible=false;scene.add(selectedBox);
let floorOverlay=null,pointerStart=null;
function geometry(g,indices=g.indices){const b=new THREE.BufferGeometry();b.setAttribute('position',new THREE.Float32BufferAttribute(g.positions,3));if(indices)b.setIndex(indices);if(g.uv)b.setAttribute('uv',new THREE.Float32BufferAttribute(g.uv,2));if(g.lightmapUv)b.setAttribute('uv1',new THREE.Float32BufferAttribute(g.lightmapUv,2));if(g.normals)b.setAttribute('normal',new THREE.Float32BufferAttribute(g.normals,3));else b.computeVertexNormals();return b;}
async function texture(id,lightmap=false){if(!id||!manifest.textures[id])return null;const key=id+(lightmap?':lm':'');if(!textures.has(key))textures.set(key,loader.loadAsync(manifest.textures[id].url).then(t=>{t.flipY=false;t.colorSpace=THREE.SRGBColorSpace;t.channel=lightmap?1:0;t.wrapS=t.wrapT=lightmap?THREE.ClampToEdgeWrapping:THREE.RepeatWrapping;return t;}));return textures.get(key);}
async function material(g){const channels=g.material.channels,diff=channels.find(c=>c.role==='diffuse')??channels.find(c=>c.role==='transparent'),light=channels.find(c=>c.role==='lightmap'),map=await texture(diff?.guid),lm=await texture(light?.guid,true);
 return {diffuse:new THREE.MeshStandardMaterial({map,color:map?0xffffff:0xb5b8ae,roughness:.93,side:THREE.DoubleSide,clippingPlanes:clipping,alphaTest:.35}),lighting:new THREE.MeshBasicMaterial({map:lm,color:lm?0xffffff:0x667781,side:THREE.DoubleSide,clippingPlanes:clipping})};}
function addMesh(root,g,indices,mats,source){if(indices?.length===0)return;const mesh=new THREE.Mesh(geometry(g,indices),mats.diffuse);root.add(mesh);mesh.userData.source=source;materials.push({mesh,...mats});pickables.push(mesh);}
function overlay(root,positions){if(!positions.length)return;const mesh=new THREE.Mesh(geometry({positions}),new THREE.MeshBasicMaterial({color:0x64eddf,wireframe:true,transparent:true,opacity:.65,depthWrite:false,clippingPlanes:clipping}));root.add(mesh);overlayObjects.push(mesh);mesh.visible=false;}
function box(bb,colour,parent=scene){const box=new THREE.Box3Helper(new THREE.Box3(new THREE.Vector3(...bb[0]),new THREE.Vector3(...bb[1])),colour);box.material.depthTest=false;box.material.transparent=true;box.material.opacity=.8;box.renderOrder=10;parent.add(box);return box;}
async function loadPark(){
 for(const m of catalog.modules){const root=new THREE.Group();roots.set(m.id,root);scene.add(root);box(m.bounds,0xffce7d,root);oldBoxes.push(box(m.bounds,0x67d9e6));}
 box([catalog.workArea[0].map((v,a)=>a===1?.025:v),catalog.workArea[1].map((v,a)=>a===1?.025:v)],0xa6e8d8);
 for(const s of manifest.sections){
  for(const model of s.models){const d=await get(model.url);for(const g of d.groups){const mats=await material(g),owned=new Set();if(model.id===catalog.renderAsset){for(const module of catalog.modules){const part=module.render.find(r=>r.section===g.sourceSection);if(!part)continue;const indices=part.triangles.flatMap(i=>{owned.add(i);return g.indices.slice(i*3,i*3+3);});addMesh(roots.get(module.id),g,indices,mats,{asset:model.id,section:g.sourceSection,triangles:part.triangles});}}
    const fixed=[],triangles=[];for(let i=0;i<g.indices.length/3;i++)if(!owned.has(i)){fixed.push(...g.indices.slice(i*3,i*3+3));triangles.push(i);}addMesh(scene,g,fixed,mats,{asset:model.id,section:g.sourceSection,triangles});}}
  for(const entry of s.collision){const d=await get(entry.url),owned=new Set();if(entry.id===catalog.simulationAsset){for(const module of catalog.modules){const positions=module.collisionUnits.flatMap(i=>{owned.add(i);return d.positions.slice(i*9,i*9+9);});overlay(roots.get(module.id),positions);}}
   const fixed=[];for(let i=0;i<d.positions.length/9;i++)if(!owned.has(i))fixed.push(...d.positions.slice(i*9,i*9+9));overlay(scene,fixed);
   for(const rail of d.rails){const module=entry.id===catalog.simulationAsset?catalog.modules.find(m=>Object.hasOwn(m.rails,rail.id)):null;const line=new THREE.Line(geometry({positions:rail.points}),new THREE.LineBasicMaterial({color:0xffd260,depthTest:false,clippingPlanes:clipping}));(module?roots.get(module.id):scene).add(line);overlayObjects.push(line);line.visible=false;}}
 }
 const floor=[];for(const mesh of pickables){const p=mesh.geometry.attributes.position.array,indices=mesh.geometry.index.array;for(let i=0;i<indices.length;i+=3){const tri=[...indices.slice(i,i+3)].map(v=>[p[v*3],p[v*3+1],p[v*3+2]]);if(tri.every(v=>Math.abs(v[1])<.003))floor.push(...tri.flat());}}
 floorOverlay=new THREE.Mesh(geometry({positions:floor}),new THREE.MeshBasicMaterial({color:0x65e1c7,transparent:true,opacity:.25,depthWrite:false,side:THREE.DoubleSide,clippingPlanes:clipping,polygonOffset:true,polygonOffsetFactor:-2}));floorOverlay.visible=false;scene.add(floorOverlay);
 const summary=catalog.inspection.summary;$('inventorySummary').textContent=`${summary.renderTriangles.toLocaleString()} triangles mapped · ${summary.connectedRegions} connected surface regions · ${summary.verifiedModules} verified movable groups`;
}
function aim(center,distance){controls.target.set(...center);camera.position.copy(controls.target).add(new THREE.Vector3(.4,1,.7).normalize().multiplyScalar(distance/Math.min(1,camera.aspect)));controls.update();}
function focusArea(){aim([32,0,60],64);}
function focusModule(id){const m=catalog.modules.find(m=>m.id===id),item=shown().modules.find(m=>m.id===id);aim([0,1,2].map(a=>(m.bounds[0][a]+m.bounds[1][a])/2+item.delta[a]),Math.max(15,(m.bounds[1][0]-m.bounds[0][0])*2));}
function checks(validation){lastValidation=validation;$('checks').classList.remove('error');$('checks').textContent=validation?.valid?'✓ Inside original boundaries\n✓ Fixed collision clear\n✓ Visible + collision floor footprints covered\n✓ Render, collision and grinds linked\nFloor repair: not needed for this arrangement':'Checks pending';$('checks').style.whiteSpace='pre-line';}
function selectedModule(){return selection?.id.startsWith('module:')?catalog.modules.find(m=>'module:'+m.id===selection.id):null;}
function canMove(){const m=selectedModule();return m&&!busy&&!candidate&&!original&&!plan.modules.find(v=>v.id===m.id).locked;}
function anchor(m){return [(m.bounds[0][0]+m.bounds[1][0])/2,m.bounds[1][1]+.25,(m.bounds[0][2]+m.bounds[1][2])/2];}
function select(hit){selection=hit;moveFeedback=hit?.id.startsWith('module:')?'Drag the group in Move mode, use the arrows, or enter X/Z offsets.':hit?'Inspection only. This region needs complete collision, grind and seam ownership before it can move.':'Click a surface to inspect it. Select a tested group to move it.';sync();$('selectionName').closest('aside').scrollTop=0;}
function updateInspector(){
 if(drag)return;
 gizmo.detach();gizmo.enabled=false;selectedBox.visible=false;
 const m=selectedModule(),item=m?shown().modules.find(v=>v.id===m.id):null;
 const region=!m&&selection?catalog.inspection.regions.find(r=>r.id===selection.id):null;
 $('selectionName').textContent=m?m.name:region?region.name:'Select a surface';
 $('selectionInfo').textContent=m?`${m.collisionUnits.length} collision triangles · ${Object.values(m.rails).reduce((a,b)=>a+b,0)} grind segments · floor retained`:region?`${region.triangles.toLocaleString()} connected render triangles. ${region.reason}`:'Click any visible surface. Three complete groups can be moved and exported.';
 $('moveFeedback').textContent=m&&item.locked?'This group is locked. Unlock it in the group list to move it.':moveFeedback;$('moveFields').hidden=!m;
 if(m){$('encodingLimits').textContent='Shared collision clusters are rebased when needed, with stationary geometry preserved. Moves must fit the original world, editing area and supporting floor. A cluster whose final span exceeds about 65.5 m still needs splitting and is rejected.';}
 $('selectTool').setAttribute('aria-pressed',String(mode==='select'));$('moveTool').setAttribute('aria-pressed',String(mode==='move'));
 if(m){$('moveX').value=item.delta[0];$('moveZ').value=item.delta[2];for(const id of ['moveX','moveZ','applyMove'])$(id).disabled=!canMove();}
 const bb=m?m.bounds.map(p=>p.map((v,a)=>v+item.delta[a])):region?.bounds;
 if(bb){selectedBox.box.set(new THREE.Vector3(...bb[0]),new THREE.Vector3(...bb[1]));selectedBox.visible=true;selectedBox.material.color.set(m?0xffd275:0xff9375);}
 if(m&&mode==='move'&&canMove()){proxy.position.set(...anchor(m).map((v,a)=>v+item.delta[a]));gizmo.attach(proxy);gizmo.enabled=true;}
 renderer.domElement.style.cursor=mode==='move'&&canMove()?'grab':'default';
}
function previewDelta(delta){
 const m=selectedModule();manualDraft=proposeMove(plan,m.id,delta);const d=manualDraft.modules.find(v=>v.id===m.id).delta;roots.get(m.id).position.set(...d);proxy.position.set(...anchor(m).map((v,a)=>v+d[a]));
 selectedBox.box.set(new THREE.Vector3(...m.bounds[0].map((v,a)=>v+d[a])),new THREE.Vector3(...m.bounds[1].map((v,a)=>v+d[a])));
 $('moveX').value=d[0];$('moveZ').value=d[2];$('moveFeedback').textContent='Preview — release to check placement. Escape cancels.';
 $('checks').textContent='Move preview · checks pending';$('checks').classList.remove('error');$('exportResult').hidden=true;
}
async function applyMove(delta){
 const m=selectedModule();if(!m||!canMove())return;
 let proposed;try{proposed=proposeMove(plan,m.id,delta);}catch(e){status(e.message,true);return;}const item=proposed.modules.find(v=>v.id===m.id);
 if(item.delta.every((v,a)=>v===plan.modules.find(v=>v.id===m.id).delta[a])){manualDraft=null;checks(lastValidation);sync();return;}
 const request=++moveRequest;manualDraft=proposed;busy=true;controls.enabled=true;moveFeedback='Checking the same limits used by Generate…';sync();status(moveFeedback);
 try{const result=await post('/api/parks/move',{plan,moduleId:m.id,delta:item.delta});if(request!==moveRequest)return;manualDraft=null;commit(result.plan);checks(result.validation);moveFeedback='Move accepted. Visible floor and collision cover both footprints; no fill was needed.';status('Move accepted with geometry, collision and grinds. Undo restores the previous placement.');}
 catch(e){if(request!==moveRequest)return;manualDraft=null;moveFeedback='Move rejected; previous placement restored. '+e.message;checks(lastValidation);status(moveFeedback,true);}
 finally{if(request===moveRequest){busy=false;sync();}}
}
function cancelMove(){
 if(!drag&&!manualDraft)return;moveRequest++;const pointerId=drag?.pointer;drag=null;manualDraft=null;pointerStart=null;gizmo.reset();gizmo.dragging=false;if(pointerId!==undefined&&renderer.domElement.hasPointerCapture(pointerId))renderer.domElement.releasePointerCapture(pointerId);controls.enabled=true;busy=false;moveFeedback='Move cancelled; previous placement retained.';checks(lastValidation);status(moveFeedback);sync();
}
function setRay(event){const b=renderer.domElement.getBoundingClientRect();pointer.set((event.clientX-b.left)/b.width*2-1,-(event.clientY-b.top)/b.height*2+1);raycaster.setFromCamera(pointer,camera);}
function pick(event){setRay(event);scene.updateMatrixWorld(true);for(const hit of raycaster.intersectObjects(pickables,false)){const id=identifyHit(hit,catalog.inspection.lookup);if(id)return id;}return null;}
function planePoint(event){setRay(event);return raycaster.ray.intersectPlane(ground,new THREE.Vector3());}
gizmo.addEventListener('dragging-changed',e=>{controls.enabled=!e.value;});
gizmo.addEventListener('mouseDown',()=>{if(canMove())drag={kind:'gizmo'};});
gizmo.addEventListener('objectChange',()=>{if(drag?.kind==='gizmo'){const origin=anchor(selectedModule());previewDelta(proxy.position.toArray().map((v,a)=>v-origin[a]));}});
gizmo.addEventListener('mouseUp',()=>{if(drag?.kind!=='gizmo')return;drag=null;controls.enabled=true;const m=selectedModule(),delta=manualDraft?.modules.find(v=>v.id===m.id).delta;if(delta)applyMove(delta);});
renderer.domElement.addEventListener('pointerdown',event=>{
 if(event.button!==0||busy||!catalog)return;pointerStart=[event.clientX,event.clientY];
 if(mode!=='move'||candidate||original||gizmo.axis)return;
 const hit=pick(event);if(!hit?.id.startsWith('module:'))return;select(hit);if(!canMove())return;
 const p=planePoint(event);if(!p)return;drag={kind:'body',start:p,delta:[...plan.modules.find(v=>v.id===selectedModule().id).delta],pointer:event.pointerId};controls.enabled=false;renderer.domElement.setPointerCapture(event.pointerId);event.stopImmediatePropagation();
},true);
renderer.domElement.addEventListener('pointermove',event=>{if(drag?.kind!=='body')return;const p=planePoint(event);if(p)previewDelta([drag.delta[0]+p.x-drag.start.x,0,drag.delta[2]+p.z-drag.start.z]);event.stopImmediatePropagation();},true);
renderer.domElement.addEventListener('pointerup',event=>{
 if(drag?.kind==='body'){const m=selectedModule(),delta=manualDraft?.modules.find(v=>v.id===m.id).delta;drag=null;controls.enabled=true;if(renderer.domElement.hasPointerCapture(event.pointerId))renderer.domElement.releasePointerCapture(event.pointerId);event.stopImmediatePropagation();pointerStart=null;if(delta)applyMove(delta);else sync();return;}
 if(event.button===0&&!busy&&!drag&&!gizmo.axis&&pointerStart&&Math.hypot(event.clientX-pointerStart[0],event.clientY-pointerStart[1])<4)select(pick(event));pointerStart=null;
},true);
renderer.domElement.addEventListener('pointercancel',cancelMove);
$('applyMove').onclick=()=>{if(busy||drag)return;if(!$('moveX').value.trim()||!$('moveZ').value.trim()){status('Enter both X and Z offsets.',true);return;}applyMove([Number($('moveX').value),0,Number($('moveZ').value)]);};
$('selectTool').onclick=()=>{if(busy||drag)return;mode='select';sync();};$('moveTool').onclick=()=>{if(busy||drag)return;mode='move';sync();};
window.addEventListener('keydown',event=>{if(event.key==='Escape'){cancelMove();return;}if($('openDialog').open||['INPUT','TEXTAREA','SELECT'].includes(event.target.tagName)||event.target.isContentEditable)return;if(event.key.toLowerCase()==='w'&&!busy&&!drag){mode='move';sync();}if(event.key.toLowerCase()==='q'&&!busy&&!drag){mode='select';sync();}if(event.key.toLowerCase()==='f'&&selectedModule()&&!drag)focusModule(selectedModule().id);const step={ArrowLeft:[-.5,0,0],ArrowRight:[.5,0,0],ArrowUp:[0,0,-.5],ArrowDown:[0,0,.5]}[event.key];if(step&&canMove()&&!drag){event.preventDefault();const d=plan.modules.find(v=>v.id===selectedModule().id).delta;applyMove(d.map((v,a)=>v+step[a]));}});
on('generate',async()=>{original=false;status('Finding a complete layout within the existing park…');const result=await post('/api/parks/generate',{plan,seed:$('seed').value});candidate=result.plan;checks(result.validation);$('exportResult').hidden=true;status('Candidate ready. Keep it to save or export; discard to retain the current layout.');});
on('keep',async()=>{commit(candidate);status('Layout accepted. Export builds and reopens the native archive for verification.');});
on('discard',async()=>{candidate=null;original=false;checks(await post('/api/parks/validate',plan));status('Candidate discarded; current layout retained.');});
on('shuffle',async()=>{$('seed').value=String(crypto.getRandomValues(new Uint32Array(1))[0]);});
on('save',async()=>{const r=await post('/api/parks/save',plan);plan=r.plan;history[at]=copy(plan);dirty=false;checks(r.validation);status('Saved locally with a versioned history.');});
on('export',async()=>{status('Building native archive, reopening it and preparing collision walk test…');const result=await post('/api/parks/export',plan);$('exportInfo').textContent=`${result.report.resourcesCompared} resources compared · geometry, collision and grind paths updated · textures preserved. ${result.path}`;$('walkExport').href=result.walkTest.url;$('download').href=result.download;$('report').href=result.reportUrl;$('exportResult').hidden=false;status('Export reopened. Open the collision walk test below; Xbox gameplay is still untested.');});
on('undo',async()=>{plan=copy(history[--at]);candidate=null;original=false;dirty=true;$('seed').value=plan.seed;$('exportResult').hidden=true;checks(await post('/api/parks/validate',plan));moveFeedback='Previous layout restored.';status(moveFeedback);});
on('redo',async()=>{plan=copy(history[++at]);candidate=null;original=false;dirty=true;$('seed').value=plan.seed;$('exportResult').hidden=true;checks(await post('/api/parks/validate',plan));moveFeedback='Next layout restored.';status(moveFeedback);});
on('restore',async()=>{commit(catalog.original);$('seed').value=plan.seed;checks(await post('/api/parks/validate',plan));status('Original layout restored locally; use Undo to return.');});
on('open',async()=>{const saved=await get('/api/parks');$('savedList').replaceChildren();if(!saved.length)$('savedList').textContent='No saved park layouts yet.';for(const item of saved){const b=document.createElement('button');b.textContent=`${item.name} · seed ${item.seed} · revision ${item.revision}`;b.onclick=async()=>{try{await openPlan(await get('/api/parks/'+encodeURIComponent(item.file)));$('openDialog').close();}catch(e){status(e.message,true);}};$('savedList').append(b);}$('openDialog').showModal();});
async function openPlan(next){checks(await post('/api/parks/validate',next));commit(next);dirty=false;$('seed').value=plan.seed;sync();status('Saved layout opened.');}
$('chooseFile').onclick=()=>$('file').click();$('closeDialog').onclick=()=>$('openDialog').close();$('file').onchange=async()=>{try{const file=$('file').files[0];if(!file)return;await openPlan(JSON.parse(await file.text()));$('openDialog').close();}catch(e){status(e.message,true);}finally{$('file').value='';}};
$('closeExport').onclick=()=>{$('exportResult').hidden=true;};
$('compare').onclick=()=>{if(busy||drag)return;original=!original;sync();};$('focus').onclick=focusArea;$('overview').onclick=()=>aim([30,0,26],145);
$('floorCoverage').onchange=()=>{if(floorOverlay)floorOverlay.visible=$('floorCoverage').checked;};
for(const id of ['collision','footprints','lighting'])$(id).onchange=sync;
new ResizeObserver(()=>{const b=$('view').getBoundingClientRect();renderer.setSize(b.width,b.height);camera.aspect=b.width/b.height;camera.updateProjectionMatrix();}).observe($('view'));
focusArea();renderer.setAnimationLoop(()=>{controls.update();renderer.render(scene,camera);});
try{const bootstrap=await get('/api/bootstrap');token=bootstrap.token;[catalog,manifest]=await Promise.all([get('/api/parks/catalog'),get('/worlds/blackbox/manifest.nxdata')]);if(manifest.sourceSha256!==catalog.sourceSha256)throw Error('Preview source differs from the native module catalog');plan=copy(catalog.original);history=[copy(plan)];await loadPark();checks(await post('/api/parks/validate',plan));status('Ready. Select a group and use Move, or generate a layout.');busy=false;sync();}catch(e){$('state').textContent='Park editor unavailable';status(e.message,true);$('checks').textContent=e.message;$('checks').classList.add('error');}
