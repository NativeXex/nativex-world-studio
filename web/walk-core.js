import {Box3,Ray,Triangle,Vector3} from 'three';
import {Capsule} from './vendor/Capsule.js';
import {Octree} from './vendor/Octree.js';

const math=new Octree(),down=new Vector3(0,-1,0),up=new Vector3(0,1,0);
const cosine=Math.cos(48*Math.PI/180);
export const SETTINGS=Object.freeze({radius:.3,height:1.75,eye:1.62,gravity:18,speed:3.2,maxSlope:48});

// A median BVH avoids duplicating long native floor triangles into octants.
export class CollisionWorld {
 constructor(){this.triangles=[];this.bounds=new Box3();this.root=null;this.degenerate=0;}
 add(data,resource){
  if(data.positions.length%9||data.surfaces.length!==data.positions.length/9||!data.positions.every(Number.isFinite))throw Error('Invalid collision triangle payload');
  for(let i=0;i<data.surfaces.length;i++){
   const p=data.positions.slice(i*9,i*9+9),t=new Triangle(new Vector3(...p.slice(0,3)),new Vector3(...p.slice(3,6)),new Vector3(...p.slice(6,9)));
   if(t.getArea()<1e-10){this.degenerate++;continue;}
   const box=new Box3().setFromPoints([t.a,t.b,t.c]);
   const entry={triangle:t,box,center:box.getCenter(new Vector3()),resource,index:i,surface:data.surfaces[i]};
   this.triangles.push(entry);this.bounds.union(box);
  }
 }
 build(){
  const split=items=>{
   const box=new Box3();for(const e of items)box.union(e.box);
   if(items.length<=16)return {box,items};
   const size=box.getSize(new Vector3()),axis=size.x>size.y?(size.x>size.z?'x':'z'):(size.y>size.z?'y':'z');
   items.sort((a,b)=>a.center[axis]-b.center[axis]);const half=items.length>>1;
   return {box,left:split(items.slice(0,half)),right:split(items.slice(half))};
  };
  if(!this.triangles.length)throw Error('No nondegenerate collision triangles');
  this.root=split(this.triangles.slice());return this;
 }
 query(box){const out=[],pending=[this.root];while(pending.length){const node=pending.pop();if(!node||!node.box.intersectsBox(box))continue;if(node.items)out.push(...node.items.filter(e=>e.box.intersectsBox(box)));else pending.push(node.left,node.right);}return out;}
 ray(ray,maxDistance=Infinity){
  let best=null;const pending=[this.root],p=new Vector3();
  while(pending.length){const n=pending.pop();if(!n||!ray.intersectsBox(n.box))continue;if(!n.items){pending.push(n.left,n.right);continue;}
   for(const e of n.items){const t=e.triangle;if(!ray.intersectTriangle(t.a,t.b,t.c,false,p))continue;const distance=p.distanceTo(ray.origin);if(distance<=maxDistance&&(!best||distance<best.distance))best={...e,point:p.clone(),distance};}
  }return best;
 }
 contacts(capsule){
  const box=new Box3().setFromPoints([capsule.start,capsule.end]).expandByScalar(capsule.radius+.002),hits=[],center=capsule.getCenter(new Vector3());
  for(const e of this.query(box)){
   let t=e.triangle;const normal=t.getNormal(new Vector3());
   // Diagnostic surfaces are deliberately two-sided. Game sidedness/material
   // responses are not inferred from the browser controller.
   if(normal.dot(center.clone().sub(t.a))<0)t=new Triangle(t.c,t.b,t.a);
   const hit=math.triangleCapsuleIntersect(capsule,t);
   if(hit&&Number.isFinite(hit.depth)&&hit.depth>0)hits.push({...hit,entry:e});
  }return hits;
 }
}

export class Walker {
 constructor(world){this.world=world;this.capsule=new Capsule(new Vector3(),new Vector3(),SETTINGS.radius);this.velocity=new Vector3();this.grounded=false;this.contact=null;this.spawn=null;this.visited=new Set();this.metrics={distance:0,seconds:0,falls:0,resets:0,contacts:0,visitedTriangles:0};}
 feet(){return this.capsule.start.clone().addScaledVector(up,-SETTINGS.radius);}
 eye(){return this.feet().addScaledVector(up,SETTINGS.eye);}
 place(point){
  const bottom=point.clone().addScaledVector(up,SETTINGS.radius+.008),top=point.clone().addScaledVector(up,SETTINGS.height-SETTINGS.radius+.008);
  const candidate=new Capsule(bottom,top,SETTINGS.radius);
  if(this.world.contacts(candidate).some(h=>h.depth>.015))throw Error('Not enough headroom or clearance here. Pick an open collision surface.');
  const support=this.world.ray(new Ray(point.clone().addScaledVector(up,.08),down),.15);
  if(!support||Math.abs(support.triangle.getNormal(new Vector3()).y)<cosine)throw Error('Choose a supported surface below the 48° walking slope limit.');
  this.capsule.copy(candidate);this.velocity.set(0,0,0);this.grounded=false;this.spawn=point.clone();return this;
 }
 autoPlace(){
  const center=this.world.bounds.getCenter(new Vector3());
  const choices=this.world.triangles.filter(e=>Math.abs(e.triangle.getNormal(new Vector3()).y)>=cosine&&e.triangle.getArea()>.6);
  choices.sort((a,b)=>(a.center.y-b.center.y)*100+Math.hypot(a.center.x-center.x,a.center.z-center.z)-Math.hypot(b.center.x-center.x,b.center.z-center.z));
  for(const e of choices.slice(0,2500)){try{return this.place(e.triangle.getMidpoint(new Vector3()));}catch{}}
  throw Error('No clear automatic start found. Pick a collision surface in the overview.');
 }
 reset(){if(!this.spawn)return;this.metrics.resets++;this.place(this.spawn);}
 jump(){if(this.grounded){this.velocity.y=6;this.grounded=false;}}
 step(seconds,direction=new Vector3(),speed=SETTINGS.speed){
  if(!this.spawn)return;
  // Fixed time and distance limits prevent a slow frame or fast fall from
  // skipping thin walls. Excess background-tab time is intentionally discarded.
  const dt=Math.min(Math.max(seconds,0),.1),before=this.feet(),desired=direction.clone();desired.y=0;if(desired.lengthSq()>1)desired.normalize();desired.multiplyScalar(Math.min(speed,5.2));
  this.velocity.x=desired.x;this.velocity.z=desired.z;
  const substeps=Math.max(1,Math.ceil(dt/(1/120)),Math.ceil((this.velocity.length()+SETTINGS.gravity*dt)*dt/.06)),h=dt/substeps;
  for(let j=0;j<substeps;j++){
   this.velocity.y-=SETTINGS.gravity*h;this.capsule.translate(this.velocity.clone().multiplyScalar(h));this.grounded=false;this.contact=null;
   for(let iteration=0;iteration<5;iteration++){
    const contacts=this.world.contacts(this.capsule).sort((a,b)=>b.depth-a.depth);if(!contacts.length)break;
    // Re-query after each correction; stale simultaneous contacts can push twice.
    const hit=contacts[0],normal=hit.normal.clone();let correction=hit.depth+1e-7;
    if(normal.y>0&&normal.y<cosine){
     // A steep incline acts as a horizontal blocker. Projecting the requested
     // walk velocity onto its full normal would inject uphill velocity each frame.
     normal.y=0;correction/=normal.length();normal.normalize();
    }
    this.capsule.translate(normal.clone().multiplyScalar(correction));
    const into=this.velocity.dot(normal);if(into<0)this.velocity.addScaledVector(normal,-into);
    if(hit.normal.y>=cosine){this.grounded=true;this.contact=hit.entry;}
    this.metrics.contacts++;this.visited.add(hit.entry.resource+':'+hit.entry.index);
   }
  }
  this.metrics.seconds+=dt;this.metrics.distance+=this.feet().distanceTo(before);this.metrics.visitedTriangles=this.visited.size;
  if(this.feet().y<this.world.bounds.min.y-8){this.metrics.falls++;const position=this.feet().toArray();this.reset();return {fell:true,position};}
  return {fell:false};
 }
}
