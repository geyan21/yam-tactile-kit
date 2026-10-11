(() => {
  "use strict";
  const data=window.ENGINEERING;
  if(!data)return;
  const element=(name,text,attributes={})=>{
    const node=document.createElement(name);if(text!==null)node.textContent=text;
    for(const [key,value] of Object.entries(attributes))node.setAttribute(key,value);
    return node;
  };
  const link=(label,href)=>element("a",label,{href});
  const canvas=document.getElementById("cad");
  const viewer=new window.MeshViewer(canvas);
  const select=document.getElementById("model-select");
  const explode=document.getElementById("explode");
  for(const model of data.models)select.append(element("option",model.title,{value:model.id}));
  const layerDefinitions={
    frame:["Original PETG frame","#657c89"],tpu:["Original TPU insert","#a8bd80"],
    saddles:["R1 cast saddles","#268479"],laminate:["R1 sensing laminate","#c66d31"],
    fixed:["Fixed carrier / shoe","#31847c"],floating:["Floating carrier / spacer","#cb8542"],
    cell:["Purchased-cell reference","#8b7eb0"],hardware:["Reserved fastener space","#555f66"],
    fixture:["Test fixture","#b79864"],tool:["Selected CAD part","#d4aa72"],
    b1tpu:["B1 magnetic TPU insert","#a8bd80"],spine:["B1 fixed sensor spine","#24897f"],
    magnet:["B1 embedded magnets","#cc8047"],plug:["B1 flush retaining plugs","#e1bf67"],pcb:["B1 fixed sensor heads","#716b9b"],
    backer:["B2 removable backer","#2e746e"],spacer:["B2 locating spacers","#78afa1"],
    electronics:["B2 component envelopes","#8374a2"],nail:["T0 / T1 thin nail pads","#d69936"],
    c1fixed:["C1 fixed carrier","#31847c"],c1floating:["C1 floating carrier","#cb8542"],
    c1beam:["C1 transverse strain beam","#788b9b"],c1clamp:["C1 end clamps","#997c57"],
    c1gauge:["C1 active strain-grid locations","#dfad3f"],
  };
  function choose(){
    const model=data.models.find(m=>m.id===select.value);
    viewer.visible=new Set(model.components.map(part=>part.group));
    viewer.setModel(model);viewer.explode=0;explode.value=0;explode.disabled=!(model.assembly||model.id==="assembly");
    document.getElementById("model-note").textContent=model.note;
    const controls=document.getElementById("layer-controls");controls.replaceChildren();
    for(const group of viewer.visible){
      const definition=group==="pcb"&&model.id.startsWith("b2")?["B2 single PCB","#48967e"]:layerDefinitions[group];
      const [label,color]=definition||[group,"#71979c"],row=element("label",null);
      const input=element("input",null,{type:"checkbox","data-layer":group,"aria-label":label});
      input.checked=true;input.addEventListener("change",()=>{input.checked?viewer.visible.add(group):viewer.visible.delete(group);viewer.draw();});
      const swatch=element("span",null,{class:"swatch"});swatch.style.backgroundColor=color;
      row.append(input,swatch,element("span",label));controls.append(row);
    }
  }
  select.addEventListener("change",choose);choose();
  document.getElementById("reset-view").addEventListener("click",()=>viewer.reset());
  explode.addEventListener("input",()=>{viewer.explode=Number(explode.value)/100;viewer.schedule();});
  for(const button of document.querySelectorAll("[data-inspect-model]")){
    button.addEventListener("click",()=>{
      select.value=button.dataset.inspectModel;choose();
      document.getElementById("design").scrollIntoView({behavior:"smooth"});select.focus({preventScroll:true});
    });
  }
  const partsBody=document.getElementById("parts-table");
  const designParts=[[data.r1,""],[data.l1,"l1/"],[data.b1,"b1/"],
    ...Object.entries(data.prototypes||{}).map(([id,plan])=>[plan,`prototypes/${id}/`])];
  for(const [design,prefix] of designParts){
    for(const part of design.parts){
      const row=element("tr",null),name=element("td",part.id.replaceAll("_"," "));
      const purpose=element("td",part.purpose);
      purpose.append(element("small",part.print_note||part.material+(part.kind==="reference_only"?" · reference envelope; follow the build guide":" · physical qualification pending")));
      const files=element("td",null);files.append(link("STEP ↓","downloads/"+prefix+part.step),link("STL ↓","downloads/"+prefix+part.stl));
      row.append(name,purpose,files);partsBody.append(row);
    }
  }
  const partCount=designParts.reduce((n,[plan])=>n+plan.parts.length,0);
  const referenceCount=designParts.reduce((n,[plan])=>n+plan.parts.filter(p=>p.kind==="reference_only").length,0);
  document.getElementById("part-count").textContent=`${partCount} digital solids, including ${referenceCount} component references`;
  document.getElementById("digital-count").textContent=partCount;
  for(const candidate of data.study.candidates){
    const row=element("tr",null),name=element("td",null),coverage=element("td",candidate.coverage),next=element("td",candidate.next),state=element("td",null);
    const target=(data.designPages||{})[candidate.id];
    name.append(target?link(candidate.name+" →",target):document.createTextNode(candidate.name));
    state.append(element("span",candidate.status,{class:"state"}));row.append(name,coverage,next,state);
    document.getElementById("candidate-table").append(row);
  }
  const ns="http://www.w3.org/2000/svg",plot=document.getElementById("result-plot");
  function svg(name,attributes,text){
    const node=document.createElementNS(ns,name);
    for(const [key,value] of Object.entries(attributes))node.setAttribute(key,String(value));
    if(text!==undefined)node.textContent=text;plot.append(node);return node;
  }
  function axes(minimum=0,maximum=20){
    plot.setAttribute("viewBox","0 0 650 360");
    plot.setAttribute("aria-label","Held-out reference force versus predicted force");
    plot.replaceChildren();svg("rect",{width:650,height:360,fill:"#fff"});
    for(let i=0;i<=4;i++){
      const x=60+i*135,y=305-i*66;
      svg("line",{x1:60,y1:y,x2:600,y2:y,stroke:"#e4e9e3"});
      svg("line",{x1:x,y1:41,x2:x,y2:305,stroke:"#e4e9e3"});
      svg("text",{x,y:325,"font-size":11,"text-anchor":"middle",fill:"#536870"},(minimum+(maximum-minimum)*i/4).toFixed(1));
      svg("text",{x:48,y:y+4,"font-size":11,"text-anchor":"end",fill:"#536870"},(minimum+(maximum-minimum)*i/4).toFixed(1));
    }
    svg("line",{x1:60,y1:305,x2:600,y2:41,stroke:"#aab8ad","stroke-dasharray":"4 4"});
    svg("text",{x:315,y:348,"text-anchor":"middle","font-size":12,fill:"#536870"},"Reference force (N)");
    svg("text",{x:20,y:25,"font-size":12,fill:"#536870"},"Predicted force (N)");
  }
  axes();
  svg("text",{x:330,y:175,"text-anchor":"middle","font-size":15,fill:"#6b7f77"},"Awaiting measured data");
  function renderContactReport(report,name){
    if(report.evidence_kind!=="physical"||!Array.isArray(report.regions)||!report.regions.length||report.regions.length>100){
      throw Error("Expected a physical contact-validation report with declared regions.");
    }
    const rows=[],ids=new Set();let total=0;
    for(const region of report.regions){
      if(typeof region.region_id!=="string"||ids.has(region.region_id))throw Error("Invalid contact region.");
      ids.add(region.region_id);
      for(const [outcome,label,color] of [["loaded","miss / unavailable","#b76a39"],["clear","false / unavailable","#347f77"]]){
        const metric=region[outcome];if(!metric)throw Error("Missing contact class.");
        for(const key of ["trials","observed_errors","unavailable_trials","conservative_errors"]){
          if(!Number.isInteger(metric[key])||metric[key]<0)throw Error("Invalid contact event count.");
        }
        if(metric.conservative_errors!==metric.observed_errors+metric.unavailable_trials||metric.conservative_errors>metric.trials){
          throw Error("Contact counts are inconsistent.");
        }
        if(metric.trials){
          if(!Number.isFinite(metric.conservative_error_rate)||Math.abs(metric.conservative_error_rate-metric.conservative_errors/metric.trials)>1e-10||
             !Number.isFinite(metric.upper_error_bound_95)||metric.upper_error_bound_95<metric.conservative_error_rate||metric.upper_error_bound_95>1){
            throw Error("Invalid contact error rate or bound.");
          }
        }else if(metric.conservative_error_rate!==null||metric.upper_error_bound_95!==null){
          throw Error("A missing class cannot have a measured rate.");
        }
        total+=metric.trials;rows.push({...metric,region:region.region_id,label,color});
      }
    }
    if(total!==report.recorded_trials)throw Error("Reported trial total differs from region counts.");
    const height=100+rows.length*26,maximum=Math.max(.02,...rows.map(row=>row.upper_error_bound_95||0))*1.05;
    plot.replaceChildren();plot.setAttribute("viewBox",`0 0 650 ${height}`);
    plot.setAttribute("aria-label","Per-region contact error rates and one-sided 95 percent upper bounds");
    svg("rect",{width:650,height,fill:"#fff"});
    svg("text",{x:20,y:22,"font-size":12,fill:"#344c55"},"Contact error rate · bound is per region and outcome");
    const x=value=>190+370*value/maximum;
    for(let i=0;i<=4;i++){
      const value=maximum*i/4;
      svg("line",{x1:x(value),x2:x(value),y1:48,y2:height-36,stroke:"#e4e9e3"});
      svg("text",{x:x(value),y:43,"font-size":10,"text-anchor":"middle",fill:"#536870"},(100*value).toFixed(1)+"%");
    }
    svg("line",{x1:x(.01),x2:x(.01),y1:48,y2:height-36,stroke:"#ac5c38","stroke-dasharray":"4 3"});
    rows.forEach((row,index)=>{
      const y=65+index*26;
      svg("text",{x:12,y:y+3,"font-size":10,fill:"#344c55"},row.region.replaceAll("_"," ").slice(0,24)+(row.label.startsWith("miss")?" · contact":" · clear"));
      if(!row.trials){svg("text",{x:190,y:y+3,"font-size":10,fill:"#536870"},"No presentations recorded");return;}
      svg("line",{x1:x(row.conservative_error_rate),x2:x(row.upper_error_bound_95),y1:y,y2:y,stroke:row.color,"stroke-width":3});
      svg("circle",{cx:x(row.conservative_error_rate),cy:y,r:4,fill:row.color});
      svg("line",{x1:x(row.upper_error_bound_95),x2:x(row.upper_error_bound_95),y1:y-5,y2:y+5,stroke:row.color,"stroke-width":2});
      svg("text",{x:580,y:y+3,"font-size":10,fill:"#344c55"},`${row.conservative_errors}/${row.trials}`);
    });
    svg("text",{x:15,y:height-13,"font-size":10,fill:"#536870"},"Dot: observed conservative rate. Whisker: 95% upper bound. Dotted line: 1% target.");
    document.getElementById("result-status").textContent=`Locally inspected: ${name}. Published specimen count remains unchanged.`;
    document.getElementById("result-metrics").textContent=
      `${report.recorded_trials}/${report.planned_trials} presentations · ${report.plan_complete?"complete":"incomplete"} plan. `+
      `Observed-rate screen: ${report.observed_rate_screen_met?"met":"not met"}. `+
      `Separate 95% bounds below 1%: ${report.per_metric_95_bound_below_1pct?"yes":"not established"}. `+
      "No simultaneous or robot qualification claim. Review the raw records and hashed event-details file.";
    plot.dataset.loaded="true";plot.dataset.reportKind="contact";
  }
  function renderReport(report,name="imported report"){
    if(report.schema==="yam-contact-validation/1"){renderContactReport(report,name);return;}
    const r1=report.schema==="yam-calibration/1",l1=["yam-l1-calibration/1","yam-l1-finger-validation/1"].includes(report.schema);
    const c1=report.schema==="yam-c1-static-validation/1";
    if(report.evidence_kind!=="physical"||(!r1&&!l1&&!c1))throw Error("Expected a physical R1, L1 or C1 force report from the bench analyzer.");
    const points=[];
    let predictions=report.predictions;
    if(c1){
      if(!Array.isArray(report.trials)||report.trials.some(row=>typeof row.available!=="boolean"))throw Error("C1 report is missing explicit hold availability.");
      predictions=report.trials.map(row=>({...row,predicted_n:row.available?row.predicted_n:null,
        contact_id:row.condition_id||row.id}));
    }
    const groups=r1?report.channels:[{channel:0,predictions}];
    if(!Array.isArray(groups))throw Error("Report is missing channels or predictions.");
    for(const channel of groups){
      if(!Number.isInteger(channel.channel)||channel.channel<0||channel.channel>5)throw Error("Invalid channel identifier.");
      if(!Array.isArray(channel.predictions))throw Error("Report is missing held-out predictions.");
      for(const point of channel.predictions){
        if(!Number.isFinite(point.reference_n)||point.reference_n<0||point.reference_n>100)throw Error("Invalid reference force.");
        if(point.predicted_n!==null&&(!Number.isFinite(point.predicted_n)||Math.abs(point.predicted_n)>100))throw Error("Invalid predicted force.");
        points.push({...point,channel:channel.channel,label:r1?`CH${channel.channel}`:String(point.contact_id||(c1?"C1":"L1"))});
      }
    }
    if(!points.length)throw Error("No held-out predictions in this report.");
    const minimum=Math.min(0,...points.filter(p=>p.predicted_n!==null).map(p=>p.predicted_n));
    const maximum=Math.max(20,...points.map(p=>p.reference_n),...points.filter(p=>p.predicted_n!==null).map(p=>p.predicted_n));
    axes(minimum,maximum);
    const colors=["#c66d31","#aa7825","#268479","#2f6987","#74a04a","#907ca8"];
    let errors=[],out=0;
    for(const point of points){
      if(point.predicted_n===null){out++;continue;}
      errors.push(point.predicted_n-point.reference_n);
      const dot=svg("circle",{cx:60+540*(point.reference_n-minimum)/(maximum-minimum),cy:305-264*(point.predicted_n-minimum)/(maximum-minimum),r:4,fill:colors[point.channel],opacity:.8});
      const title=document.createElementNS(ns,"title");title.textContent=`${point.label}: reference ${point.reference_n.toFixed(3)} N, prediction ${point.predicted_n.toFixed(3)} N`;dot.append(title);
    }
    const rmse=errors.length?Math.sqrt(errors.reduce((s,e)=>s+e*e,0)/errors.length):null;
    document.getElementById("result-status").textContent=`Locally inspected: ${name}. Published specimen count remains unchanged.`;
    document.getElementById("result-metrics").textContent=
      `${points.length} held-out ${c1?"stationary holds":"trials"} · ${out} unavailable · RMSE of available ${c1?"hold means":"trials"}: ${rmse===null?"unavailable":rmse.toFixed(3)+" N"}. `+
      (c1?"C1 static means only; dynamic force and contact reliability remain unqualified. ":"Static report only. ")+
      "Provenance and raw data require review.";
    plot.dataset.loaded="true";plot.dataset.reportKind=c1?"c1-static":"force";
  }
  document.getElementById("result-file").addEventListener("change",async e=>{
    const file=e.target.files[0];if(!file)return;
    try {
      if(file.size>2*1024*1024)throw Error("Report exceeds 2 MB.");
      renderReport(JSON.parse(await file.text()),file.name);
    } catch(error){
      axes();plot.dataset.loaded="false";document.getElementById("result-metrics").textContent="";
      document.getElementById("result-status").textContent=error.message;
    }
  });
  const locations=[...data.l1Contacts,{id:"plate_corner",u_mm:70,v_mm:-45}];
  const locationSelect=document.getElementById("load-location"),forceInput=document.getElementById("load-force");
  for(const item of locations)locationSelect.append(element("option",item.id.replaceAll("_"," "),{value:item.id}));
  function updateLoad(){
    const item=locations.find(value=>value.id===locationSelect.value),force=Number(forceInput.value);
    const moment=force*Math.hypot(item.u_mm,item.v_mm)/1000;
    document.getElementById("load-force-value").textContent=force.toFixed(1)+" N";
    document.getElementById("load-moment-value").textContent=moment.toFixed(2)+" N·m";
    document.getElementById("load-location-value").textContent=`U=${item.u_mm.toFixed(1)} mm, V=${item.v_mm.toFixed(1)} mm from the live-end screw.`;
  }
  forceInput.addEventListener("input",updateLoad);locationSelect.addEventListener("change",updateLoad);updateLoad();
  window.EngineeringUI={viewer,renderReport};
})();
