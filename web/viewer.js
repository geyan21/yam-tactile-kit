(function(){
  "use strict";
  class EnvelopeViewer {
    constructor(canvas){
      this.canvas=canvas;this.context=canvas.getContext("2d");this.yaw=-.47;this.pitch=-.48;this.explode=.2;this.model=null;
      let previous=null;
      canvas.addEventListener("pointerdown",event=>{previous=[event.clientX,event.clientY];canvas.setPointerCapture(event.pointerId);});
      canvas.addEventListener("pointermove",event=>{
        if(!previous)return;
        this.yaw+=(event.clientX-previous[0])*.012;
        this.pitch=Math.max(-1.35,Math.min(1.35,this.pitch+(event.clientY-previous[1])*.012));
        previous=[event.clientX,event.clientY];this.draw();
      });
      canvas.addEventListener("pointerup",()=>{previous=null;});
      canvas.addEventListener("pointercancel",()=>{previous=null;});
      canvas.addEventListener("keydown",event=>{
        if(!["ArrowLeft","ArrowRight","ArrowUp","ArrowDown","Home"].includes(event.key))return;
        event.preventDefault();
        if(event.key==="Home"){this.reset();return;}
        this.yaw+=(event.key==="ArrowRight"?.12:event.key==="ArrowLeft"?-.12:0);
        this.pitch=Math.max(-1.35,Math.min(1.35,this.pitch+(event.key==="ArrowDown"?.12:event.key==="ArrowUp"?-.12:0)));
        this.draw();
      });
      new ResizeObserver(()=>this.draw()).observe(canvas);
    }
    update(design){this.model=window.TactileGeometry.create(design);this.draw();}
    reset(){this.yaw=-.47;this.pitch=-.48;this.draw();}
    draw(){
      if(!this.model)return;
      const canvas=this.canvas,ctx=this.context,width=canvas.clientWidth,height=canvas.clientHeight;
      if(!width||!height)return;
      const dpr=Math.min(2,window.devicePixelRatio||1);
      canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);ctx.setTransform(dpr,0,0,dpr,0,0);
      ctx.fillStyle="#eaf0e7";ctx.fillRect(0,0,width,height);
      ctx.strokeStyle="#d7e2d2";ctx.lineWidth=.6;
      for(let x=0;x<width;x+=28){ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,height);ctx.stroke();}
      for(let y=0;y<height;y+=28){ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(width,y);ctx.stroke();}
      const vertices=this.model.components.flatMap(p=>p.vertices.map(v=>v.map((n,i)=>n+p.explosion[i]*this.explode)));
      const low=[0,1,2].map(i=>Math.min(...vertices.map(v=>v[i]))),high=[0,1,2].map(i=>Math.max(...vertices.map(v=>v[i])));
      const center=low.map((v,i)=>(v+high[i])/2);
      const rotate=v=>{
        const a=v[2]-center[2],b=v[1]-center[1],c=-(v[0]-center[0]);
        const u=a*Math.cos(this.yaw)+b*Math.sin(this.yaw),depth=-a*Math.sin(this.yaw)+b*Math.cos(this.yaw);
        return [u,depth*Math.sin(this.pitch)-c*Math.cos(this.pitch),depth*Math.cos(this.pitch)+c*Math.sin(this.pitch)];
      };
      const projected=vertices.map(rotate);
      const spanX=Math.max(...projected.map(v=>v[0]))-Math.min(...projected.map(v=>v[0]));
      const spanY=Math.max(...projected.map(v=>v[1]))-Math.min(...projected.map(v=>v[1]));
      const scale=Math.min((width-90)/Math.max(1,spanX),(height-105)/Math.max(1,spanY),8);
      const faces=[];
      for(const part of this.model.components){
        const points=part.vertices.map(v=>rotate(v.map((n,i)=>n+part.explosion[i]*this.explode)));
        for(const face of part.faces)faces.push({points:face.map(i=>points[i]),color:part.color});
      }
      faces.sort((a,b)=>a.points.reduce((s,v)=>s+v[2],0)-b.points.reduce((s,v)=>s+v[2],0));
      for(const face of faces){
        ctx.beginPath();
        face.points.forEach((v,i)=>{const x=width/2+v[0]*scale,y=height/2+v[1]*scale;i?ctx.lineTo(x,y):ctx.moveTo(x,y);});
        ctx.closePath();ctx.fillStyle=face.color;ctx.fill();ctx.strokeStyle="#497259";ctx.lineWidth=.65;ctx.stroke();
      }
      ctx.fillStyle="#5d745e";ctx.font="10px monospace";ctx.fillText("DRAG TO ROTATE · ARROW KEYS · HOME TO RESET",18,23);
      ctx.fillText("CONCEPT ENVELOPES · NOT FABRICATION CAD",18,height-18);
      canvas.dataset.rendered="true";
    }
  }
  window.EnvelopeViewer=EnvelopeViewer;
})();
