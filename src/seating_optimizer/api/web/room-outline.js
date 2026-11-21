/* Client-side placement preview; server schema remains authoritative.
 * Contract fixtures are shared with tests/test_room_geometry_contract.py.
 * This is not a separate policy for room shape persistence/validation.
 */
const EPS=1e-7;
const cross=(a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
const onEdge=(p,a,b)=>Math.abs(cross(a,b,p))<EPS &&
  Math.min(a[0],b[0])-EPS<=p[0]&&p[0]<=Math.max(a[0],b[0])+EPS &&
  Math.min(a[1],b[1])-EPS<=p[1]&&p[1]<=Math.max(a[1],b[1])+EPS;
function inside(p,polygon){
  let result=false;
  for(let i=0;i<polygon.length;i++){
    const a=polygon[i],b=polygon[(i+1)%polygon.length];
    if(onEdge(p,a,b))return true;
    if((a[1]>p[1])!==(b[1]>p[1]) &&
      p[0]<a[0]+(p[1]-a[1])*(b[0]-a[0])/(b[1]-a[1]))result=!result;
  }
  return result;
}
function covered(a,b,poly){
  if(!inside(a,poly)||!inside(b,poly))return false;
  const dx=b[0]-a[0],dy=b[1]-a[1],locations=[0,1];
  for(let i=0;i<poly.length;i++){
    const c=poly[i],d=poly[(i+1)%poly.length],ex=d[0]-c[0],ey=d[1]-c[1];
    const denom=dx*ey-dy*ex;
    if(Math.abs(denom)<EPS){
      for(const point of [c,d])if(onEdge(point,a,b))
        locations.push(Math.abs(dx)>EPS?(point[0]-a[0])/dx:(point[1]-a[1])/dy);
      continue;
    }
    const t=((c[0]-a[0])*ey-(c[1]-a[1])*ex)/denom;
    const u=((c[0]-a[0])*dy-(c[1]-a[1])*dx)/denom;
    if(t>=-EPS&&t<=1+EPS&&u>=-EPS&&u<=1+EPS)
      locations.push(Math.max(0,Math.min(1,t)));
  }
  const stops=[...new Set(locations)].sort((x,y)=>x-y);
  for(let i=1;i<stops.length;i++){
    const lo=stops[i-1],hi=stops[i];
    if(hi-lo<=EPS)continue;
    if(!inside([a[0]+dx*(lo+hi)/2,a[1]+dy*(lo+hi)/2],poly))return false;
  }
  return true;
}
export function tableFitsRoom(outline,x,y,width,height){
  if(!outline)return true;
  if(outline.length<3)return false;
  const corners=[[x,y],[x+width,y],[x+width,y+height],[x,y+height]];
  return corners.every((c,i)=>covered(c,corners[(i+1)%4],outline));
}
