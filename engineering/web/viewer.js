/* Actual indexed mesh viewer. Geometry is generated from the audited STL/CAD inputs. */
(() => {
  "use strict";
  const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];
  class MeshViewer {
    constructor(canvas) {
      this.canvas=canvas; this.ctx=canvas.getContext("2d");
      this.yaw=.28; this.pitch=.45; this.zoom=1; this.explode=0;
      this.visible=new Set(["frame","tpu","saddles","laminate","tool"]); this.model=null;
      this.request=0;
      let previous=null;
      canvas.addEventListener("pointerdown",e=>{previous=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId);});
      canvas.addEventListener("pointermove",e=>{
        if(!previous)return;
        this.yaw+=(e.clientX-previous[0])*.008;
        this.pitch=Math.max(-1.45,Math.min(1.45,this.pitch+(e.clientY-previous[1])*.008));
        previous=[e.clientX,e.clientY];this.schedule();
      });
      for(const name of ["pointerup","pointercancel","lostpointercapture"])canvas.addEventListener(name,()=>previous=null);
      canvas.addEventListener("wheel",e=>{e.preventDefault();this.zoom=Math.max(.6,Math.min(2.3,this.zoom*Math.exp(-e.deltaY*.001)));this.schedule();},{passive:false});
      canvas.addEventListener("keydown",e=>{
        if(!["ArrowLeft","ArrowRight","ArrowUp","ArrowDown","Home"].includes(e.key))return;
        e.preventDefault();
        if(e.key==="Home")this.reset();
        else {
          this.yaw+=e.key==="ArrowLeft"?-.12:e.key==="ArrowRight"?.12:0;
          this.pitch=Math.max(-1.45,Math.min(1.45,this.pitch+(e.key==="ArrowUp"?-.12:e.key==="ArrowDown"?.12:0)));
          this.schedule();
        }
      });
      new ResizeObserver(()=>this.schedule()).observe(canvas);
    }
    reset(){this.yaw=.28;this.pitch=this.model&&this.model.coordinates==="native_mm"?-.7:.6;this.zoom=1;this.schedule();}
    setModel(model){this.model=model;this.canvas.dataset.model=model.id;this.reset();}
    schedule(){if(!this.request)this.request=requestAnimationFrame(()=>{this.request=0;this.draw();});}
    draw(){
      if(!this.model||!this.ctx)return;
      const canvas=this.canvas,ctx=this.ctx,width=canvas.clientWidth,height=canvas.clientHeight;
      if(!width||!height)return;
      const dpr=Math.min(1.5,window.devicePixelRatio||1);
      canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);
      ctx.fillStyle="#f4f6f0";ctx.fillRect(0,0,width,height);
      ctx.strokeStyle="#e3e9df";ctx.lineWidth=.5;
      for(let x=20;x<width;x+=30){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,height);ctx.stroke();}
      for(let y=20;y<height;y+=30){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(width,y);ctx.stroke();}
      const native=this.model.coordinates==="native_mm";
      const canonical=v=>native?[v[1],v[2],v[0]]:v;
      const components=this.model.components.filter(part=>this.visible.has(part.group));
      let low=[Infinity,Infinity,Infinity],high=[-Infinity,-Infinity,-Infinity];
      for(const part of this.model.components)for(const vertex of part.vertices){
        const value=canonical(vertex);
        for(let i=0;i<3;i++){low[i]=Math.min(low[i],value[i]);high[i]=Math.max(high[i],value[i]);}
      }
      const center=low.map((n,i)=>(n+high[i])/2),cy=Math.cos(this.yaw),sy=Math.sin(this.yaw),cp=Math.cos(this.pitch),sp=Math.sin(this.pitch);
      const rotate=vertex=>{
        const p=canonical(vertex),x=p[0]-center[0],y=p[1]-center[1],z=p[2]-center[2];
        const a=x*cy+z*sy,c=-x*sy+z*cy;
        return [a,y*cp-c*sp,y*sp+c*cp];
      };
      let minX=Infinity,maxX=-Infinity,minY=Infinity,maxY=-Infinity;
      const prepared=components.map(part=>{
        const points=part.vertices.map(v=>rotate(v.map((n,i)=>n+part.explosion[i]*this.explode)));
        for(const p of points){minX=Math.min(minX,p[0]);maxX=Math.max(maxX,p[0]);minY=Math.min(minY,p[1]);maxY=Math.max(maxY,p[1]);}
        const rgb=[1,3,5].map(start=>parseInt(part.color.slice(start,start+2),16));
        return {part,points,rgb};
      });
      const faces=[];
      for(const {part,points,rgb} of prepared)for(const face of part.faces) {
        const p=face.map(index=>points[index]),a=p[1].map((n,i)=>n-p[0][i]),b=p[2].map((n,i)=>n-p[0][i]),normal=cross(a,b);
        const magnitude=Math.hypot(...normal)||1;
        const light=.55+.45*Math.abs((normal[0]*.25+normal[1]*.4+normal[2]*.85)/magnitude);
        faces.push({p,rgb:rgb.map(n=>Math.min(255,Math.round(n*light)))});
      }
      const scale=Math.min((width-65)/Math.max(1,maxX-minX),(height-75)/Math.max(1,maxY-minY))*this.zoom;
      const midX=(minX+maxX)/2,midY=(minY+maxY)/2;
      // Orthographic software depth buffer. Sorting entire triangles by their
      // centers gives incorrect occlusion around the real finger's holes and
      // thin overlays. Pixel depth also avoids antialiased triangle seams.
      const pixelWidth=canvas.width,pixelHeight=canvas.height;
      const image=ctx.getImageData(0,0,pixelWidth,pixelHeight),pixels=image.data;
      const depth=new Float32Array(pixelWidth*pixelHeight);depth.fill(-Infinity);
      for(const face of faces){
        const p=face.p.map(v=>[(width/2+(v[0]-midX)*scale)*dpr,(height/2-(v[1]-midY)*scale)*dpr,v[2]]);
        const [a,b,c]=p;
        const ax=c[1]-b[1],ay=b[0]-c[0],ac=-ax*b[0]-ay*b[1];
        const bx=a[1]-c[1],by=c[0]-a[0],bc=-bx*c[0]-by*c[1];
        const denominator=ax*a[0]+ay*a[1]+ac;
        if(Math.abs(denominator)<1e-8)continue;
        const inverse=1/denominator;
        const left=Math.max(0,Math.floor(Math.min(a[0],b[0],c[0]))),right=Math.min(pixelWidth-1,Math.ceil(Math.max(a[0],b[0],c[0])));
        const top=Math.max(0,Math.floor(Math.min(a[1],b[1],c[1]))),bottom=Math.min(pixelHeight-1,Math.ceil(Math.max(a[1],b[1],c[1])));
        for(let y=top;y<=bottom;y++){
          let u=(ax*(left+.5)+ay*(y+.5)+ac)*inverse,v=(bx*(left+.5)+by*(y+.5)+bc)*inverse;
          for(let x=left;x<=right;x++,u+=ax*inverse,v+=bx*inverse){
            const w=1-u-v;
            if(u< -1e-7||v< -1e-7||w< -1e-7)continue;
            const z=a[2]*u+b[2]*v+c[2]*w,index=y*pixelWidth+x;
            if(z<=depth[index]+1e-5)continue;
            depth[index]=z;
            const position=index*4;pixels[position]=face.rgb[0];pixels[position+1]=face.rgb[1];pixels[position+2]=face.rgb[2];
          }
        }
      }
      ctx.putImageData(image,0,0);
      ctx.fillStyle="#526770";ctx.font="10px system-ui";
      ctx.fillText(native?"ENPIRE BASELINE + R1 INTERFACES":"FABRICATION TOOL / CAD EXPORT",16,23);
      ctx.fillText("Digital geometry · physical fit untested",16,height-15);
      if(!components.length)ctx.fillText("Select a layer to inspect.",width/2-65,height/2);
      canvas.dataset.rendered="true";canvas.dataset.faces=String(faces.length);
    }
  }
  window.MeshViewer=MeshViewer;
})();
