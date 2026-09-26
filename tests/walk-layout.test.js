import test from 'node:test';
import assert from 'node:assert/strict';
import {Vector3,Ray} from '../web/vendor/three.module.js';
import {placementMatrix,transformCollision,testInstances} from '../web/walk-layout.js';
import {transformPoint} from '../web/level-core.js';
import {CollisionWorld} from '../web/walk-core.js';
const section={id:'native',pivot:[3,2,5]},data={positions:[2,2,4,2,2,6,4,2,6],surfaces:[42],rails:[]};
const near=(a,b)=>a.forEach((v,i)=>assert.ok(Math.abs(v-b[i])<1e-9,`${a} != ${b}`));
test('walk geometry matrix and collision use the editor pivot convention for translations and rotations',()=>{
 for(const yaw of [0,15,90,180,270]){const o={position:[-7,4,11],yaw},m=placementMatrix(o,section),d=transformCollision(data,o,section);for(let i=0;i<data.positions.length;i+=3){const point=data.positions.slice(i,i+3),wanted=transformPoint(point,o,section);near(d.positions.slice(i,i+3),wanted);near(new Vector3(...point).applyMatrix4(m).toArray(),wanted);}}
 assert.deepEqual(data.positions,[2,2,4,2,2,6,4,2,6]);
});
test('translated collision leaves its old location; duplicate is separately walkable',()=>{
 const world=new CollisionWorld(),o={position:[13,5,15],yaw:90},moved=transformCollision(data,o,section);world.add(moved,'copy');world.build();
 const center=new Vector3();for(let i=0;i<9;i+=3)center.add(new Vector3(...moved.positions.slice(i,i+3)));center.divideScalar(3);
 const hit=world.ray(new Ray(center.clone().add(new Vector3(0,3,0)),new Vector3(0,-1,0)));assert.ok(hit);assert.equal(hit.surface,42);assert.equal(hit.resource,'copy');assert.equal(world.ray(new Ray(new Vector3(3,8,5),new Vector3(0,-1,0))),null);
});
test('source walks retain identity placement while edited walks use server-filtered instances',()=>{
 const source={manifest:{sections:[section]},sectionIds:['native']},o=testInstances(source)[0];near(transformCollision(data,o,section).positions,data.positions);
 const edited={...source,instances:[{id:'clone',sectionId:'native',position:[12,0,3],yaw:90,visible:true}]};assert.equal(testInstances(edited),edited.instances);
});
