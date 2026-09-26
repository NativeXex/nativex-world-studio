import * as THREE from 'three';
import {OrbitControls} from './vendor/OrbitControls.js';
import {TransformControls} from './vendor/TransformControls.js';
import {copy,newLevel,sectionBounds,validateLevel,generateLevel,isOriginalArrangement,MAX_LEVEL_SECTIONS} from './level-core.js';

const $=id=>document.getElementById(id),esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const status=(message,error=false)=>{$('levelStatus').textContent=message;$('levelStatus').parentElement.classList.toggle('error',error);};
function on(id,fn){$(id).addEventListener('click',async()=>{try{await fn();}catch(e){status(e.message,true);console.error(e);}});}
async function get(url){const r=await fetch(url);if(!r.ok)throw Error(`Could not read ${url}`);return r.json();}
const colours=[0x62ddcd,0xe8b976,0x9aaaf1,0xef91b4];
const worldKey=new URLSearchParams(location.search).get('world')||'blackbox';
if(!/^[a-z0-9-]+$/.test(worldKey))throw Error('Invalid world reference.');
const manifest=await get(`/worlds/${worldKey}/manifest.nxdata`).catch(e=>{$('levelLoading').textContent='World unavailable. Return to the world browser.';status(e.message,true);throw e;});
if(!manifest.sections.length){$('levelLoading').textContent='This world has no decoded sections yet.';throw Error('No decoded world geometry.');}
$('walkSource').href='/walk.html?world='+worldKey;
$('walkSource').title='Opens the underlying archive without any saved or unsaved level-plan edits';
const lookup=new Map(manifest.sections.map(s=>[s.id,s]));
let walkFingerprint=null;
let project=newLevel(manifest),selected=null,candidate=null,history=[copy(project)],historyAt=0,dirty=false;
let bootstrap=null;try{bootstrap=await get('/api/bootstrap');}catch{}
let mapBuild=null,mapFingerprint=null,mapBusy=false;
const sectionExportAvailable=bootstrap?.capabilities?.blackboxSectionExport&&(worldKey==='blackbox'||worldKey.startsWith('blackbox-export-'));
function mapCurrent(){return mapBuild&&mapFingerprint===JSON.stringify(project)&&!candidate&&!dirty;}
function syncMapBuild(){
 $('buildXbox').disabled=mapBusy||!sectionExportAvailable||!!candidate||dragging;
 $('checkMapWalk').disabled=mapBusy||!mapCurrent();
 $('installMap').disabled=mapBusy||!mapCurrent()||!mapBuild?.readyToInstall;
 $('restoreMap').disabled=mapBusy||!mapBuild;
 $('restorePreviousMap').disabled=mapBusy||!mapBuild?.deployment;
 $('nativeWalk').hidden=!mapCurrent();$('mapDownload').hidden=!mapCurrent();
 if(mapBuild&&!mapCurrent())$('mapBuildStatus').textContent='Layout changed. Build and walk this arrangement before installing it.';
}
function showMapBuild(result){
 mapBuild=result;
 if(mapFingerprint===JSON.stringify(project))sessionStorage.setItem('nativex-map-build:'+project.id,result.buildId);
 $('nativeWalk').href=result.walkTest.url;$('mapDownload').href=result.download;
 const r=result.report,last=result.deployment?.events?.at(-1);
 $('mapBuildStatus').textContent=last?.event==='activated-and-byte-verified'&&last.restore?(last.restore==='previous'?'Previous working map restored and byte-verified.':'Original map restored and byte-verified.'):result.blockedByRuntimeFailure?result.nextStep:last?.event==='activated-and-byte-verified'?'Installed and byte-verified. Launch Skate 3 and test this map.':result.nextStep;
 $('mapBuildEvidence').textContent=`${r.nativeInstanceCount} native section instances · ${r.expected.collisionTriangles.toLocaleString()} collision triangles · ${r.expected.grindRails} grind rails. All ${r.resourcesCompared} resources reopened. SHA-256 ${r.outputSha256}. ${result.blockedByRuntimeFailure?'Xbox gameplay FAILED: '+result.runtime.observation:'Xbox gameplay unverified.'}`;
 syncMapBuild();
}
const source=manifest.summary;
$('sourceName').textContent=manifest.name;document.title=manifest.name+' · NativeX World Studio';
// Whole baked sections cannot currently be packed into a new connected world
// within the original boundary. Route generation to the bounded module writer.
$('generateLevel').disabled=true;
$('generateLevel').textContent='Whole-section generation unavailable';
$('levelSeed').disabled=true;$('levelGap').disabled=true;
$('planSummary').textContent='The native park generator rearranges three complete Black Box obstacle groups inside their original world and cell. District generation needs road and block segmentation first.';
const parkLink=document.createElement('a');parkLink.href='/park.html';parkLink.textContent='Open Black Box park generator →';parkLink.className='wide';$('generateLevel').after(parkLink);
$('cutaway').checked=manifest.id.startsWith('blackbox');
$('sourceSummary').textContent=`${manifest.sections.length} world sections · ${source.meshes} mesh parts · ${source.triangles.toLocaleString()} triangles`;
const subset=manifest.preservation.archiveReconstruction!=='byte-identical';
$('evidence').innerHTML=`✓ ${source.uniqueResources} resources collected${subset?' from selected source streams':''}<br>✓ ${source.textures} textures decoded<br>✓ ${source.collisionTriangles.toLocaleString()} collision triangles<br>✓ ${source.grindRails} grind rails / ${source.grindSegments} segments<br>✓ ${subset?'Selected source members preserved byte-identically':'Original archive rebuilt byte-identically'}`;
$('sourceLimits').textContent=manifest.warnings.join(' ')+` ${manifest.unsupported.length} resource components are unsupported in this preview. ${subset?'This source subset has no Xbox replacement build.':'The unchanged reconstruction has not been reloaded on Xbox.'}`;
if(manifest.gameBuild.startsWith('skate2')){
 $('nativeExportStatus').textContent='Skate 2 preview · Skate 3 export untested';
 $('exportMilestone').textContent='This is decoded Skate 2 source data. Loading it here does not prove Skate 3 can load it. Native conversion, dependency packaging and a controlled Xbox test are still required.';
}

const viewport=$('levelViewport'),renderer=new THREE.WebGLRenderer({antialias:true});
renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.setClearColor(0x111923);renderer.localClippingEnabled=true;renderer.outputColorSpace=THREE.SRGBColorSpace;
viewport.append(renderer.domElement);
const scene=new THREE.Scene(),camera=new THREE.PerspectiveCamera(48,1,.08,5000),controls=new OrbitControls(camera,renderer.domElement);
controls.enableDamping=true;controls.maxPolarAngle=Math.PI*.95;
scene.add(new THREE.HemisphereLight(0xddebff,0x687483,2.4));const sun=new THREE.DirectionalLight(0xffeddb,2.1);sun.position.set(30,90,45);scene.add(sun);
const grid=new THREE.GridHelper(600,120,0x38515c,0x263743);grid.position.y=-.35;scene.add(grid);
const clip=new THREE.Plane(new THREE.Vector3(0,-1,0),8),clipList=[clip];
const roots=new Map(),templates=new Map(),textures=new Map(),allMaterials=[];
const clipping=()=>$('cutaway').checked?clipList:[];
const raycaster=new THREE.Raycaster(),pointer=new THREE.Vector2(),selectionBox=new THREE.Box3Helper(new THREE.Box3(),0xffffff);selectionBox.visible=false;scene.add(selectionBox);
const gizmo=new TransformControls(camera,renderer.domElement);scene.add(gizmo.getHelper());gizmo.setTranslationSnap(1);gizmo.setRotationSnap(THREE.MathUtils.degToRad(15));gizmo.showY=true;gizmo.setMode('translate');gizmo.enabled=false;gizmo.visible=false;
let mode='select',dragging=false,dragSnapshot=null,flight=false,flightMouse=false;
gizmo.addEventListener('dragging-changed',e=>{dragging=e.value;controls.enabled=!e.value&&!flight;});
gizmo.addEventListener('mouseDown',()=>{dragSnapshot=copy(project);});
gizmo.addEventListener('objectChange',()=>{if(dragging)selectionBox.box.setFromObject(gizmo.object);});
gizmo.addEventListener('mouseUp',()=>{
  if(!gizmo.object||!dragSnapshot)return;
  const o=project.instances.find(x=>x.id===selected),root=gizmo.object;
  if(o&&!o.locked&&!candidate){o.position=root.position.toArray().map(v=>Math.round(v*1000)/1000);o.yaw=Math.round(THREE.MathUtils.radToDeg(root.rotation.y)/15)*15;commit();status('Section moved with its collision and grind rails.');}
  dragSnapshot=null;
});
const loader=new THREE.TextureLoader();
async function loadTexture(id){
  if(textures.has(id))return textures.get(id);
  const entry=manifest.textures[id];if(!entry)return null;
  const pending=loader.loadAsync(entry.url).then(t=>{t.colorSpace=THREE.SRGBColorSpace;t.flipY=false;t.wrapS=t.wrapT=THREE.RepeatWrapping;t.anisotropy=Math.min(8,renderer.capabilities.getMaxAnisotropy());return t;});
  textures.set(id,pending);return pending;
}
function makeGeometry(g){const b=new THREE.BufferGeometry();b.setAttribute('position',new THREE.Float32BufferAttribute(g.positions,3));if(g.indices)b.setIndex(g.indices);if(g.uv)b.setAttribute('uv',new THREE.Float32BufferAttribute(g.uv,2));if(g.normals)b.setAttribute('normal',new THREE.Float32BufferAttribute(g.normals,3));else b.computeVertexNormals();b.computeBoundingBox();return b;}
for(const s of manifest.sections){
  const template=new THREE.Group();template.position.set(...s.pivot);
  const content=new THREE.Group();content.position.set(...s.pivot.map(v=>-v));template.add(content);
  templates.set(s.id,template);
}
let geometryLoaded=0,overlayLoad=null;
const overlaysLoaded=new Set();
function hydrate(s){
  for(const o of displayed().instances.filter(o=>o.sectionId===s.id)){
    const root=roots.get(o.id);if(!root)continue;
    root.clear();for(const child of templates.get(s.id).children)root.add(child.clone(true));
    root.traverse(n=>{n.userData.instanceId=o.id;if(n.userData.layer==='collision')n.visible=$('collision').checked;if(n.userData.layer==='grind')n.visible=$('grinds').checked;});
  }
}
async function loadSection(s,i){
  const content=templates.get(s.id).children[0];
  for(const model of s.models){
    const data=await get(model.url);
    // A model typically repeats texture IDs across many mesh parts.
    await Promise.all([...new Set(data.groups.map(g=>g.material.channels.find(c=>c.role==='diffuse'||c.role==='transparent')?.guid).filter(Boolean))].map(loadTexture));
    for(const g of data.groups){
      const diffuse=g.material.channels.find(c=>c.role==='diffuse')??g.material.channels.find(c=>c.role==='transparent'),map=diffuse?await loadTexture(diffuse.guid):null;
      const mat=new THREE.MeshStandardMaterial({map:$('textured').checked?map:null,color:$('textured').checked?(map?0xffffff:0xb5b8ae):0xb0c2ca,roughness:.93,metalness:0,side:THREE.DoubleSide,clippingPlanes:clipping(),alphaTest:.35});
      mat.userData.originalMap=map;allMaterials.push(mat);
      const mesh=new THREE.Mesh(makeGeometry(g),mat);mesh.userData.layer='render';mesh.userData.materialName=g.material.name;content.add(mesh);
    }
  }
  hydrate(s);geometryLoaded++;
  $('levelLoading').textContent=`${manifest.name} · ${geometryLoaded} / ${manifest.sections.length} sections loaded`;
  await new Promise(requestAnimationFrame);
}
async function loadOverlays(s){
  if(overlaysLoaded.has(s.id))return;
  const content=templates.get(s.id).children[0],staging=new THREE.Group();
  for(const c of s.collision){
    const data=await get(c.url);
    if(data.positions.length){
      const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.Float32BufferAttribute(data.positions,3));geo.computeBoundingBox();
      const mat=new THREE.MeshBasicMaterial({color:0x64eddf,wireframe:true,transparent:true,opacity:.65,depthWrite:false,clippingPlanes:clipping()});allMaterials.push(mat);
      const mesh=new THREE.Mesh(geo,mat);mesh.visible=false;mesh.userData.layer='collision';mesh.renderOrder=2;staging.add(mesh);
    }
    for(const r of data.rails){
      const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.Float32BufferAttribute(r.points,3));
      const mat=new THREE.LineBasicMaterial({color:0xffd184,depthTest:false,clippingPlanes:clipping()});allMaterials.push(mat);
      const line=new THREE.Line(geo,mat);line.visible=false;line.userData.layer='grind';line.renderOrder=4;staging.add(line);
    }
  }
  while(staging.children.length)content.add(staging.children[0]);
  overlaysLoaded.add(s.id);hydrate(s);
}
async function ensureOverlays(){
  if(overlayLoad)return overlayLoad;
  overlayLoad=(async()=>{
    for(const s of manifest.sections){
      if(!$('collision').checked&&!$('grinds').checked)break;
      if(!overlaysLoaded.has(s.id)){status(`Loading collision and rails · ${overlaysLoaded.size+1} / ${manifest.sections.length}`);await loadOverlays(s);await new Promise(requestAnimationFrame);}
    }
    sync();status('Requested world overlays loaded locally.');
  })().finally(()=>{overlayLoad=null;});
  return overlayLoad;
}
const levelBoxes=[];
function drawOverview(current){
  const svg=$('worldOverview'),boxes=current.instances.filter(o=>o.visible).map(o=>({o,b:sectionBounds(o,lookup.get(o.sectionId))}));
  if(!boxes.length){svg.replaceChildren();return;}
  const lo=[Math.min(...boxes.map(x=>x.b.min[0])),Math.min(...boxes.map(x=>x.b.min[2]))],hi=[Math.max(...boxes.map(x=>x.b.max[0])),Math.max(...boxes.map(x=>x.b.max[2]))];
  const width=Math.max(1,hi[0]-lo[0]),height=Math.max(1,hi[1]-lo[1]),pad=Math.max(width,height)*.03;
  svg.setAttribute('viewBox',`${lo[0]-pad} ${lo[1]-pad} ${width+2*pad} ${height+2*pad}`);
  boxes.sort((a,b)=>(b.b.max[0]-b.b.min[0])*(b.b.max[2]-b.b.min[2])-(a.b.max[0]-a.b.min[0])*(a.b.max[2]-a.b.min[2]));
  svg.innerHTML=boxes.map(({o,b},i)=>`<rect data-instance="${esc(o.id)}" x="${b.min[0]}" y="${b.min[2]}" width="${Math.max(.3,b.max[0]-b.min[0])}" height="${Math.max(.3,b.max[2]-b.min[2])}" fill="${o.id===selected?'#a4e9d8':'#345f65'}" fill-opacity="${o.id===selected?'.8':'.4'}" stroke="${o.id===selected?'#edfffa':'#77999f'}" stroke-width="${Math.max(width,height)*.0015}"><title>Section ${esc(o.sectionId)} · click to focus</title></rect>`).join('');
}
function displayed(){return candidate?.project??project;}
function sync(){
  syncMapBuild();
  $('walkReady').hidden=!!candidate||walkFingerprint!==JSON.stringify(project);
  // A restore/removal may replace the selected root. Detach before the next
  // scene-matrix update so TransformControls never observes an orphan.
  gizmo.detach();
  const current=displayed(),ids=new Set(current.instances.map(o=>o.id));
  for(const [id,root] of roots)if(!ids.has(id)){scene.remove(root);roots.delete(id);}
  for(const o of current.instances){
    let root=roots.get(o.id);
    if(!root){root=templates.get(o.sectionId).clone(true);root.traverse(n=>{n.userData.instanceId=o.id;});roots.set(o.id,root);scene.add(root);}
    root.position.set(...o.position);root.rotation.set(0,THREE.MathUtils.degToRad(o.yaw),0);root.visible=o.visible;
    root.traverse(n=>{if(n.userData.layer==='collision')n.visible=$('collision').checked;if(n.userData.layer==='grind')n.visible=$('grinds').checked;});
  }
  for(const box of levelBoxes){scene.remove(box);box.geometry.dispose();box.material.dispose();}levelBoxes.length=0;
  if($('sectionBoxes').checked)for(const [i,o] of current.instances.entries()){
    if(!o.visible)continue;const b=sectionBounds(o,lookup.get(o.sectionId)),box=new THREE.Box3Helper(new THREE.Box3(new THREE.Vector3(...b.min),new THREE.Vector3(...b.max)),colours[i%4]);scene.add(box);levelBoxes.push(box);
  }
  scene.updateMatrixWorld(true);
  $('levelName').value=project.name;$('levelSeed').value=project.seed;
  $('saveStatus').textContent=dirty?'Unsaved level plan':project.savedAt?'Saved level plan · '+new Date(project.savedAt*1000).toLocaleTimeString():'Original source loaded';
  $('previewBadge').textContent=candidate?'Candidate · preview only':isOriginalArrangement(project,manifest)?'Original arrangement':'Edited arrangement · local preview';
  $('previewBadge').classList.toggle('candidate',!!candidate);
  $('candidateButtons').hidden=!candidate;
  $('sections').innerHTML=current.instances.map((o,i)=>{const s=lookup.get(o.sectionId);if(!s.id.toLowerCase().includes($('sectionSearch').value.toLowerCase()))return '';return `<button class="worldSection ${selected===o.id?'selected':''}" data-instance="${esc(o.id)}"><div><span class="swatch" style="background:#${colours[i%4].toString(16)}"></span>Section ${esc(s.id)}<small>${s.models.reduce((n,m)=>n+m.triangles,0).toLocaleString()} triangles · ${o.origin==='copy'?'copy':'source'}</small></div><span>${o.locked?'🔒':o.visible?'':'○'}</span></button>`;}).join('');
  $('sections').querySelectorAll('button').forEach(b=>b.onclick=()=>select(b.dataset.instance));
  $('levelStats').textContent=`${current.instances.filter(o=>o.visible).length} world sections · ${current.instances.filter(o=>o.visible).reduce((n,o)=>n+lookup.get(o.sectionId).models.reduce((n,m)=>n+m.triangles,0),0).toLocaleString()} render triangles`;
  $('undoLevel').disabled=historyAt===0||!!candidate;$('redoLevel').disabled=historyAt===history.length-1||!!candidate;
  drawOverview(current);
  updateSelection();
}
function commit(){$('walkReady').hidden=true;const v=validateLevel(project,manifest);if(v.errors.length)throw Error(v.errors.join(' '));history=history.slice(0,historyAt+1);history.push(copy(project));if(history.length>80)history.shift();historyAt=history.length-1;dirty=true;sync();}
function editable(){if(candidate)throw Error('Keep or discard the candidate before editing.');const o=project.instances.find(x=>x.id===selected);if(!o)throw Error('Select a world section.');if(o.locked)throw Error('Unlock this section first.');return o;}
function select(id){selected=id;sync();}
function updateSelection(){
  const o=displayed().instances.find(x=>x.id===selected),root=roots.get(selected);gizmo.detach();selectionBox.visible=!!o&&o.visible;
  if(!o){$('sectionInspector').innerHTML='<h3>Select part of the world</h3><p>Its geometry, collision and grind rails move together in the preview.</p>';return;}
  const s=lookup.get(o.sectionId);if(root)selectionBox.box.setFromObject(root);
  if(root&&o.visible&&!o.locked&&!candidate&&mode!=='select'){gizmo.attach(root);gizmo.enabled=true;gizmo.visible=true;}else{gizmo.enabled=false;gizmo.visible=false;}
  const disabled=candidate?'disabled':'';
  $('sectionInspector').innerHTML=`<h3>World section ${esc(s.id)}</h3><p>Baked geometry · ${s.models.reduce((n,m)=>n+m.meshes,0)} mesh parts<br>${s.collision.reduce((n,c)=>n+c.triangles,0).toLocaleString()} collision triangles · ${s.rails.reduce((n,r)=>n+r.count,0)} grind rails</p><div class="rowfields">${['X','Y','Z'].map((n,i)=>`<label>${n} · m<input id="section${n}" type="number" step="1" value="${o.position[i].toFixed(3)}" ${disabled}></label>`).join('')}</div><label>Rotation Y · degrees<input id="sectionYaw" type="number" step="15" value="${o.yaw}" ${disabled}></label><button id="setSection" class="wide" ${disabled}>Apply transform</button><div class="rowfields"><button id="lockSection" ${disabled}>${o.locked?'Unlock':'Lock'}</button><button id="hideSection" ${disabled}>${o.visible?'Hide':'Show'}</button></div><div class="rowfields"><button id="copySection" ${disabled}>Duplicate</button><button id="removeSection" ${disabled}>Remove</button></div><p>Shared source data stays intact. This edit applies to the saved level plan and its preview.</p>`;
  on('setSection',()=>{const item=editable();const pos=['X','Y','Z'].map(n=>Number($('section'+n).value)),yaw=Number($('sectionYaw').value);if(!pos.every(v=>Number.isFinite(v)&&Math.abs(v)<100000)||!Number.isFinite(yaw)||yaw%15)throw Error('Use finite positions and 15° rotation steps.');item.position=pos;item.yaw=yaw;commit();status('Section transform updated; collision and rails use the same transform.');});
  on('lockSection',()=>{if(candidate)return;const item=project.instances.find(x=>x.id===selected);item.locked=!item.locked;commit();});
  on('hideSection',()=>{const item=editable();item.visible=!item.visible;commit();});
  on('copySection',()=>{const item=copy(editable());if(project.instances.length>=MAX_LEVEL_SECTIONS)throw Error(`Level plan limit: ${MAX_LEVEL_SECTIONS} sections.`);item.id=crypto.randomUUID();item.origin='copy';item.position[0]+=10;project.instances.push(item);selected=item.id;commit();});
  on('removeSection',()=>{editable();project.instances=project.instances.filter(x=>x.id!==selected);selected=null;commit();});
}
function fit(ids){
  const all=displayed().instances.filter(o=>o.visible&&(!ids||ids.includes(o.id)));if(!all.length)return;
  const box=new THREE.Box3();for(const o of all){const b=sectionBounds(o,lookup.get(o.sectionId));box.union(new THREE.Box3(new THREE.Vector3(...b.min),new THREE.Vector3(...b.max)));}
  const center=box.getCenter(new THREE.Vector3()),size=box.getSize(new THREE.Vector3()),extent=Math.max(size.x,size.z,size.y*2,10);
  camera.far=Math.max(5000,extent*8/Math.min(1,camera.aspect));camera.updateProjectionMatrix();
  controls.target.copy(center);camera.position.copy(center).add(new THREE.Vector3(.55,.9,.75).normalize().multiplyScalar(extent*1.35/Math.min(1,camera.aspect)));camera.lookAt(center);controls.update();
}
function setMode(next){mode=next;gizmo.setMode(next==='rotate'?'rotate':'translate');gizmo.showX=next!=='rotate';gizmo.showZ=next!=='rotate';gizmo.showY=true;for(const name of ['select','move','rotate'])$(name+'Mode').classList.toggle('active',name===next);updateSelection();}
on('selectMode',()=>setMode('select'));on('moveMode',()=>setMode('move'));on('rotateMode',()=>setMode('rotate'));
on('focusAll',()=>fit());on('focusSelection',()=>fit(selected?[selected]:null));
on('undoLevel',()=>{if(historyAt>0&&!candidate){project=copy(history[--historyAt]);dirty=true;sync();}});on('redoLevel',()=>{if(historyAt<history.length-1&&!candidate){project=copy(history[++historyAt]);dirty=true;sync();}});
on('restore',()=>{candidate=null;const fresh=newLevel(manifest);fresh.id=project.id;fresh.name=project.name;project=fresh;selected=null;commit();fit();status('Original world arrangement restored. Undo retains the previous layout.');});
$('levelName').onchange=()=>{if(candidate){sync();return;}project.name=$('levelName').value.slice(0,200);commit();};
on('generateLevel',()=>{candidate=generateLevel(project,manifest,$('levelSeed').value,Number($('levelGap').value));$('planSummary').textContent=candidate.plan.note;sync();$('levelSeed').value=candidate.plan.seed;fit();status('Candidate preview: section spacing is intentional; connecting terrain is not generated.');});
on('acceptLevel',()=>{if(!candidate)return;if(candidate.base!==JSON.stringify(project))throw Error('The source plan changed. Generate again.');project=candidate.project;candidate=null;commit();status('Arrangement kept. Undo returns to the preceding level.');});
on('discardLevel',()=>{candidate=null;sync();fit();status('Candidate discarded. Your level plan is unchanged.');});
for(const id of ['collision','grinds'])$(id).onchange=()=>{sync();if($(id).checked)ensureOverlays().catch(e=>status('Overlay load failed: '+e.message,true));};
$('sectionBoxes').onchange=sync;$('sectionSearch').oninput=sync;
$('worldOverview').onclick=e=>{const id=e.target.dataset.instance;if(id){select(id);fit([id]);}};
$('textured').onchange=()=>{for(const m of allMaterials)if('originalMap'in m.userData){m.map=$('textured').checked?m.userData.originalMap:null;m.color.set($('textured').checked?(m.userData.originalMap?0xffffff:0xb5b8ae):0xb0c2ca);m.needsUpdate=true;}};
$('cutaway').onchange=()=>{for(const m of allMaterials){m.clippingPlanes=$('cutaway').checked?clipList:[];m.needsUpdate=true;}};
on('togglePanel',()=>document.body.classList.toggle('showLevelInspector'));

async function post(path,body){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-NativeX-Token':bootstrap?.token??''},body:JSON.stringify(body)});const value=await r.json();if(!r.ok)throw Error(value.error??'Save failed');return value;}
function download(p){const a=document.createElement('a');const url=URL.createObjectURL(new Blob([JSON.stringify(p,null,2)],{type:'application/json'}));a.href=url;a.download=p.id+'.nxlevel.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
on('saveLevel',async()=>{
  if(candidate)throw Error('Keep or discard the candidate before saving.');
  project.name=$('levelName').value.slice(0,200);
  const snapshot=copy(project),fingerprint=JSON.stringify(project),v=validateLevel(snapshot,manifest);if(v.errors.length)throw Error(v.errors.join(' '));
  if(bootstrap?.capabilities?.levelPlans){const result=await post('/api/levels/save',snapshot);if(JSON.stringify(project)===fingerprint){project=result.project;history[historyAt]=copy(project);dirty=false;sync();}status('Level plan saved to '+result.path);}
  else{download(snapshot);status('Level plan file downloaded. Open it here to continue editing.');}
});
on('buildXbox',async()=>{
 if(candidate||dragging)throw Error('Finish the current edit before building.');
 mapBusy=true;syncMapBuild();
 try{
  bootstrap=await get('/api/bootstrap');
  const snapshot=copy(project);snapshot.name=$('levelName').value.slice(0,200);
  const before=JSON.stringify(project);
  $('mapBuildStatus').textContent='Saving the layout and compiling native map records…';
  const saved=dirty||!project.savedAt?await post('/api/levels/save',snapshot):{project:snapshot};
  if(JSON.stringify(project)!==before)throw Error('The layout changed while saving. Build again.');
  project=saved.project;history[historyAt]=copy(project);dirty=false;mapFingerprint=JSON.stringify(project);
  const result=await post('/api/levels/build',copy(project));showMapBuild(result);
  status('Native map built and reopened. Open exported walk, test a route, and save its report.');
 }catch(e){$('mapBuildStatus').textContent=e.message;throw e;}
 finally{mapBusy=false;sync();}
});
on('checkMapWalk',async()=>{if(!mapCurrent())throw Error('Build the current layout first.');showMapBuild(await get('/api/level-builds/'+mapBuild.buildId));});
on('installMap',async()=>{
 if(!mapCurrent())throw Error('The layout changed. Rebuild and walk it first.');
 mapBusy=true;syncMapBuild();$('mapBuildStatus').textContent='Checking Aurora, preserving backups, and transferring the verified map…';
 try{bootstrap=await get('/api/bootstrap');showMapBuild(await post('/api/levels/install',{buildId:mapBuild.buildId,plan:copy(project)}));status('Installed map and backups verified by full readback. Launch Skate 3 and test.');}
 catch(e){$('mapBuildStatus').textContent=e.message;throw e;}
 finally{mapBusy=false;syncMapBuild();}
});
on('restoreMap',async()=>{
 mapBusy=true;syncMapBuild();$('mapBuildStatus').textContent='Checking Aurora and restoring the original map…';
 try{bootstrap=await get('/api/bootstrap');showMapBuild(await post('/api/levels/restore-original',{buildId:mapBuild.buildId}));status('Original Xbox map restored and byte-verified.');}
 catch(e){$('mapBuildStatus').textContent=e.message;throw e;}
 finally{mapBusy=false;syncMapBuild();}
});
on('restorePreviousMap',async()=>{
 mapBusy=true;syncMapBuild();$('mapBuildStatus').textContent='Checking Aurora and restoring the previous working map…';
 try{bootstrap=await get('/api/bootstrap');showMapBuild(await post('/api/levels/restore-previous',{buildId:mapBuild.buildId}));status('Previous working Xbox map restored and byte-verified.');}
 catch(e){$('mapBuildStatus').textContent=e.message;throw e;}
 finally{mapBusy=false;syncMapBuild();}
});
on('walkEdited',async()=>{
  if(candidate||dragging)throw Error('Finish the move or keep/discard the candidate before walking.');
  $('walkEdited').disabled=true;
  try{
    const snapshot=copy(project);snapshot.name=$('levelName').value.slice(0,200);
    bootstrap=await get('/api/bootstrap');
    status('Preparing a walk snapshot of this arrangement, including copies and transforms…');
    const fingerprint=JSON.stringify(snapshot),result=await post('/api/levels/walk',snapshot);
    const current=copy(project);current.name=$('levelName').value.slice(0,200);
    if(JSON.stringify(current)!==fingerprint){status('The layout changed while preparing. Click Walk edited layout again to capture the new arrangement.',true);return;}
    walkFingerprint=fingerprint;
    $('walkReady').href=result.url;$('walkReady').hidden=false;
    status('Edited layout ready. Open edited walk to test this exact arrangement locally. No native archive was exported.');
  }finally{$('walkEdited').disabled=false;}
});
async function openProject(p){$('walkReady').hidden=true;const v=validateLevel(p,manifest);if(v.errors.length)throw Error(v.errors.join(' '));project=copy(p);candidate=null;selected=null;history=[copy(p)];historyAt=0;dirty=false;sync();fit();status('Level plan reopened with its original source identity and section transforms.');}
on('openLevel',async()=>{
  if(!bootstrap?.capabilities?.levelPlans){$('levelFile').click();return;}
  const list=(await get('/api/levels')).filter(p=>p.sourceId===manifest.id);
  $('levelSaved').replaceChildren();
  if(!list.length)$('levelSaved').textContent='No saved plans for '+manifest.name+'.';
  for(const p of list){
    const b=document.createElement('button');b.textContent=p.name;
    b.onclick=async()=>{try{await openProject(await get('/api/levels/'+encodeURIComponent(p.file)));$('levelOpenDialog').close();}catch(e){status(e.message,true);}};
    $('levelSaved').append(b);
  }
  $('levelOpenDialog').showModal();
});
on('openLevelFile',()=>{$('levelOpenDialog').close();$('levelFile').click();});on('closeLevelDialog',()=>$('levelOpenDialog').close());
$('levelFile').onchange=async e=>{try{if(e.target.files[0])await openProject(JSON.parse(await e.target.files[0].text()));}catch(err){status(err.message,true);}e.target.value='';};

let down=null;renderer.domElement.addEventListener('pointerdown',e=>{down=[e.clientX,e.clientY];flightMouse=flight&&e.button===0;});
renderer.domElement.addEventListener('pointerup',e=>{
  flightMouse=false;if(!down||Math.hypot(e.clientX-down[0],e.clientY-down[1])>4||dragging||gizmo.axis)return;down=null;
  const r=renderer.domElement.getBoundingClientRect();pointer.set((e.clientX-r.left)/r.width*2-1,-(e.clientY-r.top)/r.height*2+1);raycaster.setFromCamera(pointer,camera);
  const hit=raycaster.intersectObjects([...roots.values()],true).find(h=>h.object.userData.layer==='render'&&roots.get(h.object.userData.instanceId).visible&&(!$('cutaway').checked||h.point.y<=8));
  selected=hit?.object.userData.instanceId??null;sync();
});
renderer.domElement.addEventListener('pointermove',e=>{if(!flightMouse)return;const angle=new THREE.Euler().setFromQuaternion(camera.quaternion,'YXZ');angle.y-=e.movementX*.004;angle.x=THREE.MathUtils.clamp(angle.x-e.movementY*.004,-1.5,1.5);camera.quaternion.setFromEuler(angle);});
on('fly',()=>{flight=!flight;flightMouse=false;controls.enabled=!flight;$('fly').classList.toggle('active',flight);$('levelCrosshair').hidden=!flight;if(!flight){const d=new THREE.Vector3();camera.getWorldDirection(d);controls.target.copy(camera.position).addScaledVector(d,30);controls.update();}status(flight?'Flight: drag to look · WASD move · Q/E down/up · Shift faster.':'Orbit camera enabled.');});
const keys=new Set();window.addEventListener('keydown',e=>{
  if(/INPUT|TEXTAREA|SELECT/.test(e.target.tagName))return;
  keys.add(e.code);if(['KeyW','KeyA','KeyS','KeyD','KeyQ','KeyE','Space'].includes(e.code))e.preventDefault();
  if(!flight){if(e.code==='KeyW')setMode('move');if(e.code==='KeyE')setMode('rotate');if(e.code==='KeyQ')setMode('select');if(e.code==='KeyF')fit(selected?[selected]:null);}
  if((e.metaKey||e.ctrlKey)&&e.code==='KeyZ'){e.preventDefault();$(e.shiftKey?'redoLevel':'undoLevel').click();}
});window.addEventListener('keyup',e=>keys.delete(e.code));window.addEventListener('blur',()=>{keys.clear();flightMouse=false;});
window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
new ResizeObserver(()=>{const w=viewport.clientWidth,h=viewport.clientHeight;renderer.setSize(w,h,false);camera.aspect=w/h;camera.updateProjectionMatrix();}).observe(viewport);
let last=performance.now();function frame(now){requestAnimationFrame(frame);const dt=Math.min(.05,(now-last)/1000);last=now;if(flight){const speed=(keys.has('ShiftLeft')?65:22)*dt,forward=new THREE.Vector3(),right=new THREE.Vector3();camera.getWorldDirection(forward);right.crossVectors(forward,camera.up).normalize();if(keys.has('KeyW'))camera.position.addScaledVector(forward,speed);if(keys.has('KeyS'))camera.position.addScaledVector(forward,-speed);if(keys.has('KeyD'))camera.position.addScaledVector(right,speed);if(keys.has('KeyA'))camera.position.addScaledVector(right,-speed);if(keys.has('KeyE'))camera.position.y+=speed;if(keys.has('KeyQ'))camera.position.y-=speed;}else controls.update();renderer.render(scene,camera);}
sync();camera.aspect=viewport.clientWidth/viewport.clientHeight;camera.updateProjectionMatrix();fit();requestAnimationFrame(frame);
try{
  // Bounded loading keeps the UI responsive and avoids decoding hundreds of
  // model JSON files and images simultaneously on a laptop.
  let cursor=0;await Promise.all(Array.from({length:Math.min(3,manifest.sections.length)},async()=>{while(cursor<manifest.sections.length){const i=cursor++;await loadSection(manifest.sections[i],i);}}));
  const params=new URLSearchParams(location.search),snapshotId=params.get('layout'),savedFile=params.get('plan');
  if(snapshotId)await openProject(await get('/api/level-walk-plans/'+encodeURIComponent(snapshotId)));
  else if(savedFile)await openProject(await get('/api/levels/'+encodeURIComponent(savedFile)));
  const remembered=sessionStorage.getItem('nativex-map-build:'+project.id);
  if(remembered&&/^[a-f0-9]{64}$/.test(remembered)){
   try{const result=await get('/api/level-builds/'+remembered);if(JSON.stringify(result.report.plan)===JSON.stringify(project)){mapFingerprint=JSON.stringify(project);showMapBuild(result);}}catch{}
  }
  $('levelLoading').hidden=true;$('walkEdited').disabled=false;sync();
  status(snapshotId||savedFile?'Saved arrangement reopened with its copies and transforms. Use Walk edited layout to test it.':`${manifest.name} loaded locally. ${manifest.importStatus==='ready-preview'?'':'Partial import — see import evidence. '}Select a world section to inspect or rearrange it.`);
}catch(e){$('levelLoading').textContent='Some world data could not load. Return to the world browser and reopen to retry.';status(e.message,true);console.error(e);}
