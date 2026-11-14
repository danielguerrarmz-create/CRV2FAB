// node tests/test_core.js — curvature maths on analytic surfaces and billet fit on a known arc
require('../src/core.js'); require('../src/billet.js'); const C=globalThis.Core, B=globalThis.Billet;
let fails=0; const near=(name,got,exp,tol)=>{ const ok=Math.abs(got-exp)<=tol; if(!ok) fails++; console.log(`${ok?'ok  ':'FAIL'} ${name}: ${got.toFixed(4)} (expected ${exp}±${tol})`); };
const R=6000, sph=(u,v)=>{const x=(u-0.5)*4000,y=(v-0.5)*3000;return [x,y,Math.sqrt(R*R-x*x-y*y)];};
let r=C.analyzePatch(sph,{u0:0,u1:1,v0:0,v1:1},31,31,false), i=15*31+15;
near('sphere K*R^2',r.K[i]*R*R,1,1e-4); near('sphere |H|*R',Math.abs(r.H[i])*R,1,1e-4);
const cyl=(u,v)=>{const t=(v-0.5)*1.5;return [u*4000,3000*Math.sin(t),3000*Math.cos(t)]};
r=C.analyzePatch(cyl,{u0:0,u1:1,v0:0,v1:1},21,21,false); i=10*21+10; near('cylinder K',r.K[i],0,1e-12); near('cylinder |k2|*R',Math.abs(r.k2[i])*3000,1,1e-4);
const sad=(u,v)=>[u*4000,v*3000,600*((2*u-1)**2-(2*v-1)**2)];
r=C.analyzePatch(sad,{u0:0,u1:1,v0:0,v1:1},21,21,false); i=10*21+10; near('saddle R1',1/r.k1[i],3333.333,0.5); near('saddle R2',1/r.k2[i],-1875,0.5);
// billet: pure arc beam R=6000, 400 deep x 200 wide, 60 deg
const pts=[]; for(let k=0;k<=60;k++){ const th=k/60*Math.PI/3; for(const d of [-200,0,200]) for(const w of [-100,0,100]) pts.push([(6000-d)*Math.cos(th),(6000-d)*Math.sin(th),w]); }
const b=B.fitBillet(pts,{lamT:40,allow:0,level:'full'}); near('billet radius',b.R,6000,5); near('billet depth',b.depth,400,0.5); near('billet width',b.width,200,0.5); near('lam count',b.lamCount,10,0);
console.log(fails? `${fails} FAILED` : 'all passed'); process.exit(fails?1:0);
