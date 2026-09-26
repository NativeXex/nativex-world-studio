import test from 'node:test';
import assert from 'node:assert/strict';
import {snapDelta,proposeMove,identifyHit} from '../web/park-edit.js';

test('manual proposal snaps on the floor and leaves the accepted plan untouched',()=>{
 const plan={modules:[{id:'pad',delta:[0,0,0],locked:false}]};
 const next=proposeMove(plan,'pad',[-1.3,0,4.2]);
 assert.deepEqual(next.modules[0].delta,[-1.5,0,4]);
 assert.deepEqual(plan.modules[0].delta,[0,0,0]);
 assert.throws(()=>snapDelta([NaN,0,1]),/finite/);
 assert.throws(()=>proposeMove(plan,'floor',[1,0,1]),/verified/);
 plan.modules[0].locked=true;
 assert.throws(()=>proposeMove(plan,'pad',[1,0,1]),/Unlock/);
});

test('selection resolves original triangle identity after a material batch is split',()=>{
 const lookup={asset:{301:['surface-001','module:pad','surface-002','module:pad']}};
 const hit={point:{y:1},faceIndex:1,object:{userData:{source:{asset:'asset',section:301,triangles:[1,3]}}}};
 assert.deepEqual(identifyHit(hit,lookup),{id:'module:pad',asset:'asset',section:301,triangle:3});
 hit.object.userData.source.triangles=[0,2];
 assert.equal(identifyHit(hit,lookup).id,'surface-002');
 hit.point.y=7;
 assert.equal(identifyHit(hit,lookup),null);
 hit.point.y=1;hit.faceIndex=4;
 assert.equal(identifyHit(hit,lookup),null);
});
