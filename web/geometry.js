(function(root){
  "use strict";
  const Model=root.TactileModel || (typeof require!=="undefined"?require("./model.js"):null);
  const quads=[[0,1,2,3],[4,5,6,7],[0,4,5,1],[1,5,6,2],[2,6,7,3],[3,7,4,0]];
  const sub=(a,b)=>a.map((v,i)=>v-b[i]);
  const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
  function part(id,title,color,vertices,explosion){
    const center=[0,1,2].map(i=>vertices.reduce((s,v)=>s+v[i],0)/vertices.length);
    const faces=[];
    for(const q of quads)for(const f of [[q[0],q[1],q[2]],[q[0],q[2],q[3]]]){
      const [a,b,c]=f.map(i=>vertices[i]),n=cross(sub(b,a),sub(c,a));
      const middle=[0,1,2].map(i=>(a[i]+b[i]+c[i])/3);
      if(n.reduce((s,v,i)=>s+v*(middle[i]-center[i]),0)<0)[f[1],f[2]]=[f[2],f[1]];
      faces.push(f);
    }
    return {id,title,color,vertices,faces,explosion,envelope_only:true};
  }
  function box(id,title,color,low,high,explosion){
    const [x0,y0,z0]=low,[x1,y1,z1]=high;
    return part(id,title,color,[[x0,y0,z0],[x1,y0,z0],[x1,y1,z0],[x0,y1,z0],[x0,y0,z1],[x1,y0,z1],[x1,y1,z1],[x0,y1,z1]],explosion);
  }
  function create(input){
    const d=Model.validate(input),r=Model.evaluate(d),L=d.finger_length_mm,W=d.face_width_mm,T=d.body_thickness_mm,N=d.nose_thickness_mm;
    const sw=Math.max(12,W+4),sd=Math.max(8,T+2),mw=Math.max(14,W+6),md=Math.max(10,T+4),cx=-T/2;
    const components=[
      box("mount","Fixed mount placeholder","#8c9d91",[cx-md/2,-mw/2,-32],[cx+md/2,mw/2,-20],[0,0,-22]),
      box("sensor","Force module placeholder","#609b83",[cx-sd/2,-sw/2,-18],[cx+sd/2,sw/2,-2],[0,0,-10]),
      part("finger","Thin finger envelope","#bdd5bf",[[-T,-W/2,0],[0,-W/2,0],[0,W/2,0],[-T,W/2,0],[-N,-W/2,L],[0,-W/2,L],[0,W/2,L],[-N,W/2,L]],[0,0,0])
    ];
    const gap=Math.min(2,Math.max(0,(L-d.pad_length_mm)/2));
    if(r.taxels&&d.pad_stack_mm>0)components.push(box("pad","Pressure laminate allowance","#c89453",[-d.pad_recess_mm,-W/2,L-gap-d.pad_length_mm],[d.pad_stack_mm-d.pad_recess_mm,W/2,L-gap],[8,0,0]));
    return {schema_version:1,kind:"concept_envelopes",units:"mm",geometry_status:d.geometry_status,hardware_validated:false,
      frame:{x:"inward normal",y:"finger width",z:"distal finger"},
      assumptions:{mount_length_mm:12,sensor_length_mm:16,mount_width_mm:mw,mount_depth_mm:md,sensor_width_mm:sw,sensor_depth_mm:sd,status:"Illustrative packaging assumptions; no selected force element or measured mounting interface."},
      limitations:["Generic envelopes, not the user's exact finger or a manufactured sensor.","No mounting holes, calibrated flexures, cable channels, or production tolerances.","Laminate overlap represents a recess allowance, not a finished mating pocket.","The force-plot stations form a separate ideal model; these boxes do not model strain gauges."],
      components};
  }
  root.TactileGeometry={create};
  if(typeof module!=="undefined"&&module.exports)module.exports={create};
})(typeof globalThis!=="undefined"?globalThis:window);
