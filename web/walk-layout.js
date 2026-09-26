import {Matrix4,Vector3} from 'three';

// Exactly the editor's parent translation / Y rotation / inverse source pivot.
// Both visible geometry and physics use this matrix for every visible instance.
export function placementMatrix(instance,section){
 return new Matrix4().makeTranslation(...instance.position)
  .multiply(new Matrix4().makeRotationY(instance.yaw*Math.PI/180))
  .multiply(new Matrix4().makeTranslation(...section.pivot.map(v=>-v)));
}
export function transformCollision(data,instance,section){
 const matrix=placementMatrix(instance,section),positions=new Array(data.positions.length),point=new Vector3();
 for(let i=0;i<data.positions.length;i+=3){point.fromArray(data.positions,i).applyMatrix4(matrix);point.toArray(positions,i);}
 return {...data,positions};
}
export function testInstances(source){
 return source.instances??source.manifest.sections.filter(s=>source.sectionIds.includes(s.id)).map(s=>({id:s.id,sectionId:s.id,position:s.pivot,yaw:0,visible:true,origin:'original'}));
}
