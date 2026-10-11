/* Lazy, local-only use of the already released assembly meshes. */
(() => {
  "use strict";
  const details=document.querySelector("[data-design-viewer]");
  if(!details)return;
  let viewer=null;
  function start(){
    if(viewer||!details.open)return;
    const canvas=details.querySelector("canvas");
    const model=window.ENGINEERING?.models.find(item=>item.id===canvas.dataset.modelId);
    if(!model||!window.MeshViewer)return;
    viewer=new window.MeshViewer(canvas);
    viewer.visible=new Set(model.components.map(part=>part.group));
    viewer.setModel(model);
    details.querySelector(".design-viewer-note").textContent=model.note;
    const labels={frame:model.id==="nail_assembly"?"N1 revised frame":"Original frame",tpu:"Original TPU",saddles:"R1 saddles",laminate:"R1 sensing laminates",
      fixed:"Fixed carrier",floating:"Floating carrier",cell:"Cell reference",hardware:"Reserved fasteners",
      b1tpu:"Magnetic TPU",spine:"Fixed spine",magnet:"Magnets",plug:"Retaining plugs",
      pcb:model.id==="b2_assembly"?"One B2 PCB":"Sensor heads",
      backer:"Removable backer",spacer:"Locating spacers",electronics:"IC / component envelopes",nail:"T0 / T1 nail pads",
      c1fixed:"Fixed root carrier",c1floating:"Floating finger carrier",c1beam:"Transverse strain beam",
      c1clamp:"Beam end clamps",c1gauge:"Eight active strain-grid locations",
      nailbody:"N1 bare fork and sensing webs",nailleft:"Left fixed carrier",nailright:"Right fixed carrier",
      nailgauges:"NL / NR foil-carrier locations"};
    const controls=details.querySelector(".design-viewer-layers");
    for(const group of viewer.visible){
      const label=document.createElement("label"),input=document.createElement("input");
      input.type="checkbox";input.checked=true;input.dataset.designLayer=group;
      input.addEventListener("change",()=>{
        input.checked?viewer.visible.add(group):viewer.visible.delete(group);viewer.draw();
      });
      label.append(input,document.createTextNode(labels[group]||group));controls.append(label);
    }
    details.querySelector("[data-reset-design-view]").addEventListener("click",()=>viewer.reset());
    details.querySelector("[data-design-explode]").addEventListener("input",event=>{
      viewer.explode=Number(event.target.value)/100;viewer.schedule();
    });
    window.DesignPageViewer=viewer;
    viewer.draw();
  }
  details.addEventListener("toggle",start);
  start();
})();
