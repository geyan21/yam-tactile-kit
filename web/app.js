(function () {
  "use strict";
  const data = window.TACTILE_KIT_DATA;
  if (!data) return;
  document.querySelectorAll(".repo-link").forEach(link => {
    if (data.repository_url) {
      link.href = data.repository_url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.hidden = false;
    }
  });
  if (!document.getElementById("assembly-view")) return;

  const model = window.TactileModel;
  let state = model.validate(data.design);
  let selected = "finger";
  let exploded = 35;
  const $ = id => document.getElementById(id);
  const fmt = (value, digits=2) => Number(value).toFixed(digits).replace(/\.0+$/,"").replace(/(\.\d*?)0+$/,"$1");
  const svgText = (x,y,text,size=13,fill="#536b5d",extra="") => `<text x="${x}" y="${y}" font-family="Arial,sans-serif" font-size="${size}" fill="${fill}" ${extra}>${text}</text>`;
  const controls = [
    ["geometry-controls","face_width_mm","Contact-face width",1,20,0.5],
    ["geometry-controls","pad_length_mm","Pad length",4,50,1],
    ["geometry-controls","pad_border_mm","Border / side",0,4,0.25],
    ["geometry-controls","cell_pitch_mm","Cell pitch",0.5,5,0.25],
    ["advanced-controls","finger_length_mm","Finger length",20,150,1],
    ["advanced-controls","nose_thickness_mm","Nose thickness",0.1,5,0.1],
    ["advanced-controls","body_thickness_mm","Body thickness",1,15,0.5],
    ["advanced-controls","pad_stack_mm","Pad stack",0,4,0.1],
    ["advanced-controls","pad_recess_mm","Seat recess",0,4,0.1],
    ["advanced-controls","station_spacing_mm","Station spacing",2,30,0.5],
    ["force-controls","contact_distance_mm","Contact position · mm",13,60,0.5],
    ["force-controls","applied_force_n","Applied force · N",0,40,0.25],
    ["force-controls","end_moment_nmm","End moment · N·mm",-100,100,5],
    ["budget-controls","mass_kg","Object mass · kg",0,3,0.05],
    ["budget-controls","friction_coefficient","Friction coefficient",0.05,1,0.05],
    ["budget-controls","static_load_factor","Static load factor",1,3,0.1],
    ["budget-controls","sensor_force_n","Sensor range / jaw · N",1,100,1],
    ["budget-controls","allowed_adapter_deflection_mm","Adapter deflection · mm",0.01,0.5,0.01]
  ];
  const partText = {
    finger:["01","Replaceable thin finger","Retain the working leading edge and compliance. Place the service interface at the root."],
    sensor:["02","Calibrated force-sensing base","All normal finger loads pass through this element. Specify stiffness, off-center response, overload protection, and a repeatable mount."],
    pad:["03","Optional local pressure strip","Use a small defined seat when contact location helps. Route the tail and connector back toward the root."]
  };

  function setStatus(message,error=false) {
    $("input-status").textContent = message;
    $("input-status").classList.toggle("error",error);
  }
  function syncControls() {
    for (const [,key,,minimum,maximum] of controls) {
      const number = $(`number-${key}`);
      const slider = $(`range-${key}`);
      if (!number) continue;
      let low=minimum,high=maximum;
      if (key==="contact_distance_mm") { low=state.station_spacing_mm+0.1; high=state.finger_length_mm; }
      slider.min=Math.min(low,state[key]);
      slider.max=Math.max(high,state[key]);
      number.value=state[key];
      slider.value=state[key];
    }
  }
  function commit(key,value) {
    try {
      const next = {...state,[key]:value};
      if (key==="finger_length_mm" && next.contact_distance_mm>value) next.contact_distance_mm=value;
      if (key==="station_spacing_mm" && next.contact_distance_mm<=value) next.contact_distance_mm=value+0.5;
      state=model.validate(next);
      setStatus("Updated in this browser. Export JSON to save these settings.");
      render();
    } catch (error) {
      syncControls();
      setStatus(`${error.message}. Previous valid design retained.`,true);
    }
  }
  for (const [container,key,label,minimum,maximum,step] of controls) {
    const field=document.createElement("div");
    field.className="field";
    const top=document.createElement("div");
    top.className="field-top";
    const name=document.createElement("label");
    name.htmlFor=`number-${key}`;
    name.textContent=label;
    const number=document.createElement("input");
    number.type="number";number.id=`number-${key}`;number.className="field-value";
    number.step="any";number.min=model.ranges[key][0];number.max=model.ranges[key][1];
    number.setAttribute("aria-label",label);
    number.addEventListener("change",()=>commit(key,number.value.trim()===""?NaN:Number(number.value)));
    top.append(name,number);
    const slider=document.createElement("input");
    slider.type="range";slider.id=`range-${key}`;slider.min=minimum;slider.max=maximum;slider.step=step;
    slider.setAttribute("aria-label",`${label} slider`);
    slider.addEventListener("input",()=>commit(key,Number(slider.value)));
    field.append(top,slider);$(container).append(field);
  }

  function drawAssembly(r) {
    const e=exploded*0.58;
    const start=362+e,end=935+e;
    const scale=(end-start)/state.finger_length_mm;
    const body=Math.min(90,Math.max(36,state.body_thickness_mm*13));
    const nose=Math.max(4,body*state.nose_thickness_mm/state.body_thickness_mm);
    const top=182-body/2,bottom=182+body/2,tipTop=210-nose/2,tipBottom=210+nose/2;
    const contact=start+state.contact_distance_mm*scale;
    const contactY=bottom+(tipBottom-bottom)*(state.contact_distance_mm/state.finger_length_mm);
    const fillFinger=selected==="finger"?"#c9ded0":"#d8e4d9";
    const fillSensor=selected==="sensor"?"#75ac95":"#a8c8b2";
    const padEnd=end-16,padStart=Math.max(start+20,padEnd-state.pad_length_mm*scale);
    const padY=x=>bottom+(tipBottom-bottom)*((x-start)/(end-start));
    const sensorX=201+e/3;
    $("assembly-view").innerHTML=`
      <defs><marker id="force-arrow" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><path d="M0 0 L8 4 L0 8 Z" fill="#a9723e"/></marker>
      <pattern id="mount-hatch" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(35)"><line x1="0" y1="0" x2="0" y2="8" stroke="#b0bcae" stroke-width="2"/></pattern></defs>
      <line x1="66" y1="182" x2="1018" y2="182" stroke="#b6c8b5" stroke-dasharray="5 7"/>
      <rect x="82" y="116" width="89" height="136" rx="7" fill="url(#mount-hatch)" stroke="#8ea18b" stroke-width="1.7"/>
      <rect x="${sensorX}" y="135" width="103" height="96" rx="9" fill="${fillSensor}" stroke="#487f62" stroke-width="2.5"/>
      <rect x="${sensorX+21}" y="152" width="61" height="19" rx="8" fill="#eaf0e7" stroke="#487f62" stroke-width="1.5"/>
      <rect x="${sensorX+21}" y="194" width="61" height="19" rx="8" fill="#eaf0e7" stroke="#487f62" stroke-width="1.5"/>
      <rect x="${sensorX+13}" y="137" width="18" height="7" rx="2" fill="#bd8a4b"/>
      <rect x="${sensorX+73}" y="222" width="18" height="7" rx="2" fill="#bd8a4b"/>
      <rect x="${start-31}" y="${top-17}" width="31" height="${body+34}" rx="5" fill="#749f89" stroke="#46765a" stroke-width="1.5"/>
      <path d="M${start} ${top} L${start+105} ${top} Q${start+310} ${top+12} ${end} ${tipTop} L${end} ${tipBottom} Q${start+290} ${bottom-3} ${start+105} ${bottom} L${start} ${bottom} Z" fill="${fillFinger}" stroke="#4b7a5e" stroke-width="2.5"/>
      ${r.taxels?`<path d="M${padStart} ${padY(padStart)} L${padEnd} ${padY(padEnd)}" stroke="${selected==="pad"?"#b47837":"#c69861"}" stroke-width="${selected==="pad"?10:7}" stroke-linecap="round"/>`:""}
      <path d="M${padStart} ${padY(padStart)+5} Q${start+140} 278 ${sensorX+54} 282" fill="none" stroke="#bf9254" stroke-width="2.5" stroke-dasharray="7 6"/>
      <rect x="${sensorX-5}" y="265" width="121" height="34" rx="5" fill="#315e48"/>
      ${svgText(sensorX+13,287,"ADC + ID + plug",13,"#eff5e9")}
      <line x1="${contact}" y1="${contactY+84}" x2="${contact}" y2="${contactY+18}" stroke="#a9723e" stroke-width="3" marker-end="url(#force-arrow)"/>
      ${svgText(contact+12,contactY+65,`${fmt(state.applied_force_n)} N`,16,"#97612b")}
      <circle cx="${contact}" cy="${contactY+5}" r="5" fill="#bd8c4d"/>
      ${svgText(79,102,"FIXED JAW",11,"#6b7f6a")}
      ${svgText(sensorX-5,108,"FORCE ELEMENT",11,"#496f55")}
      <path d="M${start+110} ${top-7} L${start+145} 79 L${start+276} 79" fill="none" stroke="#7b9779" stroke-width="1.2"/>
      ${svgText(start+150,67,"THIN REPLACEABLE FINGER",12,"#476747")}
      <path d="M${padEnd-16} ${padY(padEnd)-6} L${padEnd-40} 128 L${padEnd-121} 128" fill="none" stroke="#a69164" stroke-width="1.2"/>
      ${svgText(padEnd-250,116,"OPTIONAL PRESSURE STRIP",11,"#9b723d")}
      ${svgText(80,349,`Finger length input ${fmt(state.finger_length_mm)} mm · nose ${fmt(state.nose_thickness_mm)} mm`,13,"#5b775c")}
      ${svgText(80,374,"Conceptual shapes. Mounting geometry and structural behavior are unverified.",11,"#80907c")}
    `;
  }

  function drawPad(r) {
    const w=state.face_width_mm,l=state.pad_length_mm;
    const scale=Math.min(360/w,152/l);
    const pw=w*scale,ph=l*scale,x=215-pw/2,y=42;
    let cells="";
    if (r.taxels<=1024) {
      for(let row=0;row<r.rows;row++) for(let col=0;col<r.columns;col++) {
        const size=state.cell_pitch_mm*scale;
        cells+=`<rect x="${x+(state.pad_border_mm+col*state.cell_pitch_mm)*scale}" y="${y+(state.pad_border_mm+row*state.cell_pitch_mm)*scale}" width="${Math.max(.1,size-1.2)}" height="${Math.max(.1,size-1.2)}" rx="1.5" fill="#c49b65"/>`;
      }
    }
    $("pad-view").innerHTML=`
      <rect x="${x}" y="${y}" width="${pw}" height="${ph}" rx="4" fill="#e8e4d4" stroke="#b4a583" stroke-width="1.4"/>${cells}
      <line x1="${x}" y1="${y-13}" x2="${x+pw}" y2="${y-13}" stroke="#94a68b"/>
      <line x1="${x}" y1="${y-18}" x2="${x}" y2="${y-8}" stroke="#94a68b"/>
      <line x1="${x+pw}" y1="${y-18}" x2="${x+pw}" y2="${y-8}" stroke="#94a68b"/>
      ${svgText(215,y-23,`${fmt(w)} mm face`,12,"#657758",'text-anchor="middle"')}
      ${svgText(215,y+ph+25,`${fmt(l)} mm pad length`,12,"#657758",'text-anchor="middle"')}
      ${svgText(415,79,`${r.columns} × ${r.rows}`,26,"#274d39")}
      ${svgText(415,104,"PROPOSED GRID",10,"#7c8b72")}
      ${svgText(415,140,`${fmt(state.pad_border_mm)} mm border`,12)}
      ${svgText(415,164,`${fmt(state.cell_pitch_mm)} mm cell pitch`,12)}
      ${svgText(415,194,r.taxels>1024?"Grid omitted at this density":r.taxels?"Cell envelopes only":"No full cells fit",11,r.taxels?"#7c8b72":"#a65e36")}
    `;
    $("pad-title").textContent=r.taxels?"A small seat, not a full wrap.":"No complete cell fits this envelope.";
  }

  function drawForce(r) {
    const left=58,right=720,top=25,bottom=244;
    const loX=state.station_spacing_mm+0.1,hiX=state.finger_length_mm;
    const single=z=>(state.applied_force_n*z+state.end_moment_nmm)/state.finger_length_mm;
    const minY=Math.min(0,single(loX),single(hiX));
    const maxY=Math.max(1,state.applied_force_n,single(loX),single(hiX))*1.16;
    const y0=minY<0?minY*1.15:0;
    const X=z=>left+(z-loX)/(hiX-loX)*(right-left);
    const Y=f=>bottom-(f-y0)/(maxY-y0)*(bottom-top);
    let lines="";
    for(let i=0;i<5;i++) {
      const v=y0+(maxY-y0)*i/4;
      lines+=`<line x1="${left}" y1="${Y(v)}" x2="${right}" y2="${Y(v)}" stroke="#e4e9de"/>${svgText(left-10,Y(v)+4,fmt(v,1),10,"#798873",'text-anchor="end"')}`;
    }
    for(let i=0;i<5;i++) {
      const v=loX+(hiX-loX)*i/4;
      lines+=svgText(X(v),bottom+22,fmt(v,1),10,"#798873",'text-anchor="middle"');
    }
    $("force-plot").innerHTML=`
      ${lines}
      <line x1="${left}" y1="${bottom}" x2="${right}" y2="${bottom}" stroke="#b9c9b3"/>
      <path d="M${X(loX)} ${Y(single(loX))} L${X(hiX)} ${Y(single(hiX))}" stroke="#c39155" stroke-width="3" fill="none"/>
      <path d="M${left} ${Y(state.applied_force_n)} L${right} ${Y(state.applied_force_n)}" stroke="#287464" stroke-width="3" fill="none"/>
      <line x1="${X(state.contact_distance_mm)}" y1="${top}" x2="${X(state.contact_distance_mm)}" y2="${bottom}" stroke="#a7b6a1" stroke-dasharray="5 5"/>
      <circle cx="${X(state.contact_distance_mm)}" cy="${Y(r.recovered_normal_force_n)}" r="6" fill="#287464" stroke="white" stroke-width="2"/>
      <circle cx="${X(state.contact_distance_mm)}" cy="${Y(single(state.contact_distance_mm))}" r="5" fill="#c39155" stroke="white" stroke-width="2"/>
      ${svgText(left,13,"Force · N",11)}
      ${svgText((left+right)/2,285,"Contact distance from the first station · mm",11,"#708267",'text-anchor="middle"')}
    `;
  }

  function drawCalibration() {
    const c=data.calibration,points=c.held_out_predictions;
    const max=Math.max(1,...points.flatMap(p=>[p.reference_force_n,p.predicted_force_n]))*1.08;
    const min=Math.min(0,...points.map(p=>p.predicted_force_n));
    const lo=min<0?min-.1:0;
    const X=v=>67+(v-lo)/(max-lo)*564,Y=v=>288-(v-lo)/(max-lo)*248;
    let chart="";
    for(let i=0;i<=4;i++) {
      const value=lo+(max-lo)*i/4;
      chart+=`<line x1="67" y1="${Y(value)}" x2="631" y2="${Y(value)}" stroke="#e5e9df"/>
      ${svgText(56,Y(value)+3,fmt(value,1),10,"#7d8a76",'text-anchor="end"')}
      ${svgText(X(value),311,fmt(value,1),10,"#7d8a76",'text-anchor="middle"')}`;
    }
    chart+=`<path d="M${X(lo)} ${Y(lo)} L${X(max)} ${Y(max)}" fill="none" stroke="#b2c5ac" stroke-dasharray="5 6" stroke-width="1.5"/>`;
    for(const point of points) chart+=`<circle cx="${X(point.reference_force_n)}" cy="${Y(point.predicted_force_n)}" r="5" fill="#448671" fill-opacity=".58" stroke="#2a6b55" stroke-width=".6"/>`;
    chart+=svgText(68,17,"Predicted force · N",11)+svgText(350,340,"Reference force · N",11,"#6d8064",'text-anchor="middle"');
    $("calibration-plot").innerHTML=chart;
    $("dataset-badge").textContent=c.dataset_kind==="synthetic"?"SYNTHETIC DATA · NOT SENSOR PERFORMANCE":"SUPPLIED MEASUREMENTS · NOT HARDWARE QUALIFICATION";
    $("calibration-train").textContent=c.training_samples;
    $("calibration-test").textContent=c.held_out_samples;
    $("calibration-rmse").textContent=`${fmt(c.held_out_rmse_n,4)} N`;
    $("calibration-scope").textContent=c.scope;
    if(c.dataset_kind==="measured") {
      document.querySelector(".calibration-copy>p").textContent="This build fits and evaluates the supplied measured calibration CSV. Independent hardware qualification, uncertainty, and operating-condition checks remain necessary.";
    }
  }

  function render() {
    const r=model.evaluate(state);
    syncControls();
    $("geometry-label").textContent=state.geometry_status==="illustrative"?"ILLUSTRATIVE GEOMETRY":"MEASURED INPUTS / UNVERIFIED DESIGN";
    $("taxel-count").textContent=r.taxels;
    $("grid-shape").textContent=`${r.columns} columns × ${r.rows} rows`;
    $("active-envelope").textContent=`${fmt(r.active_width_mm)} × ${fmt(r.active_length_mm)}`;
    $("net-count").textContent=r.electrode_nets;
    $("opening-loss").textContent=fmt(r.opening_loss_mm);
    $("moment-1").textContent=fmt(r.moment_1_nmm,1);
    $("moment-2").textContent=fmt(r.moment_2_nmm,1);
    $("recovered-force").textContent=`${fmt(r.recovered_normal_force_n)} N`;
    $("static-force").textContent=`${fmt(r.required_static_force_per_jaw_n)} N`;
    $("stiffness").textContent=`${fmt(r.minimum_adapter_stiffness_n_per_mm)} N/mm`;
    $("design-issues").replaceChildren();
    for(const issue of r.issues) {
      const p=document.createElement("p");p.className="issue";p.textContent=issue;$("design-issues").append(p);
    }
    drawAssembly(r);drawPad(r);drawForce(r);
  }

  function importDesign(value) {
    state=model.validate(value);
    render();
    setStatus(`Imported “${state.label}”. Review the geometry status before using these inputs.`);
    return {...state};
  }
  function reset() {
    state=model.validate(data.design);render();setStatus("Example restored. Changes stay in this browser until exported.");
  }
  $("reset-design").addEventListener("click",reset);
  $("explode").addEventListener("input",event=>{exploded=Number(event.target.value);drawAssembly(model.evaluate(state));});
  document.querySelectorAll("[data-part]").forEach(button=>button.addEventListener("click",()=>{
    selected=button.dataset.part;
    document.querySelectorAll("[data-part]").forEach(b=>b.classList.toggle("active",b===button));
    const [number,title,description]=partText[selected];
    $("part-number").textContent=number;$("part-title").textContent=title;$("part-description").textContent=description;
    drawAssembly(model.evaluate(state));
  }));
  $("export-design").addEventListener("click",()=>{
    const content=JSON.stringify(state,null,2)+"\n";
    const blob=new Blob([content],{type:"application/json"});
    const url=URL.createObjectURL(blob);
    const anchor=document.createElement("a");anchor.href=url;anchor.download="yam-tactile-design.json";
    document.body.append(anchor);anchor.click();anchor.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
    window.TactileKit.lastExport=content;
    setStatus("Design JSON exported. Rebuild with this file to preserve the same calculations.");
  });
  $("import-design").addEventListener("click",()=>$("design-file").click());
  $("design-file").addEventListener("change",async event=>{
    const file=event.target.files[0];if(!file)return;
    try {
      if(file.size>131072)throw new Error("Design JSON must be smaller than 128 KiB");
      importDesign(JSON.parse(await file.text()));
    } catch(error){setStatus(`Import rejected: ${error.message}`,true);}
    event.target.value="";
  });

  for(const ref of data.references) {
    const row=document.createElement("article");row.id=`source-${ref.id}`;
    const id=document.createElement("span");id.className="reference-id";id.textContent=ref.id;
    const body=document.createElement("div"),title=document.createElement("h3"),link=document.createElement("a"),note=document.createElement("p");
    link.href=ref.url;link.target="_blank";link.rel="noopener noreferrer";link.textContent=`${ref.title} ↗`;
    title.append(link);note.textContent=ref.note;body.append(title,note);row.append(id,body);$("reference-list").append(row);
  }
  document.querySelectorAll('a[href^="#source-"]').forEach(link=>link.addEventListener("click",()=>{
    document.querySelector(".source-details").open=true;
  }));
  window.TactileKit={getDesign:()=>({...state}),getSummary:()=>model.evaluate(state),importDesign,reset,lastExport:null};
  drawCalibration();render();
  document.documentElement.dataset.kitReady="true";
})();
