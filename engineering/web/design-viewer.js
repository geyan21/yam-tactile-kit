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
    const labels={frame:model.id==="nail_assembly"?"N1 revised frame":model.id==="recessed_assembly"?"B3 recessed frame":"Original frame",tpu:"Original TPU",saddles:"R1 saddles",laminate:"R1 sensing laminates",
      fixed:"Fixed carrier",floating:"Floating carrier",cell:"Cell reference",hardware:"Reserved fasteners",
      b1tpu:"Magnetic TPU",spine:"Fixed spine",magnet:"Magnets",plug:"Retaining plugs",
      pcb:model.id==="fb1_assembly_reference"?"FMA sensor PCB":["b2_assembly","recessed_assembly"].includes(model.id)?"One B2 PCB":"Sensor heads",
      backer:"Removable backer",spacer:model.id==="recessed_assembly"?"B3 tapered spacers":"Locating spacers",electronics:"IC / component envelopes",nail:"T0 / T1 nail pads",
      c1fixed:"Fixed root carrier",c1floating:"Floating finger carrier",c1beam:"Transverse strain beam",
      c1clamp:"Beam end clamps",c1gauge:"Eight active strain-grid locations",
      nailbody:"N1 bare fork and sensing webs",nailleft:"Left fixed carrier",nailright:"Right fixed carrier",
      nailgauges:"NL / NR foil-carrier locations",
      f1_stacks:"Film and electrode reference bodies",f1_tails:"Tail fit references",
      f1_board:["f1_r3_assembly_reference","f1_r4_assembly_reference"].includes(model.id)?"R3 PCB fit reference":"R2 PCB fit reference",f1_carrier:"Removable carrier",
      f1_components:"Component body envelopes",f1_fastener_envelopes:"Reserved fasteners",
      f1_foils:"Complete flexible electrode envelopes",f1_film:"Six pressure-film islands",f1_covers:"Retained silicone covers",
      f1_fit_bases:"Compliant fitting bases",f1_stack_bonds:"Mounting and foot bonds",f1_stiffeners:"Terminal PI and adhesive pieces",
      support:"Compliant sensor backing",leaves:"Four steel guides",clamps:"Guide clamps",
      sensor:"Honeywell FMA envelope",plunger:"Adjustable plunger",insulation:"PCB insulating film",
      pcb_components:"Bypass capacitors",root_hardware:"Root fasteners",stops:"Adjustable overload stops",
      k1_plates:"Grounded steel plates",k1_covers:"Vented silicone retainers",k1_plate_bonds:"Two plate-ground bond envelopes",
      k1_stops:"Polyimide stop quadrants",k1_flex:"Guarded flexible electrodes",k1_terminals:"Stiffeners and solder envelopes",
      k1_saddles:"Conforming rigid TPU supports",
      p1_insert:"P1 soft insert",p1_front_air:"Front gas spaces (references)",p1_back_air:"Back gas spaces (references)",
      p1_hardware:"Metal fittings and plugs",p1_seals:"Bond/seal envelopes",p1_hoses:"Local hose segments",p1_nails:"Two thin N0 nail cells"};
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
