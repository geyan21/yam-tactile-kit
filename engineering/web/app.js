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
  function choose(){
    const model=data.models.find(m=>m.id===select.value);
    viewer.setModel(model);viewer.explode=0;explode.value=0;explode.disabled=model.id!=="assembly";
    document.getElementById("model-note").textContent=model.note;
  }
  select.addEventListener("change",choose);choose();
  document.getElementById("reset-view").addEventListener("click",()=>viewer.reset());
  explode.addEventListener("input",()=>{viewer.explode=Number(explode.value)/100;viewer.schedule();});
  for(const [group,label,color] of [
    ["frame","Original PETG frame","#657c89"],["tpu","Original TPU insert","#a8bd80"],
    ["saddles","R1 cast saddles","#268479"],["laminate","R1 sensing laminate","#c66d31"],
  ]){
    const row=element("label",null),input=element("input",null,{type:"checkbox","data-layer":group,"aria-label":label});
    input.checked=true;input.addEventListener("change",()=>{input.checked?viewer.visible.add(group):viewer.visible.delete(group);viewer.draw();});
    const swatch=element("span",null,{class:"swatch"});swatch.style.backgroundColor=color;
    row.append(input,swatch,element("span",label));document.getElementById("layer-controls").append(row);
  }
  const partsBody=document.getElementById("parts-table");
  for(const part of data.r1.parts){
    const row=element("tr",null),name=element("td",part.id.replaceAll("_"," "));
    const purpose=element("td",part.purpose);purpose.append(element("small",part.print_note));
    const files=element("td",null);files.append(link("STEP ↓","downloads/"+part.step),link("STL ↓","downloads/"+part.stl));
    row.append(name,purpose,files);partsBody.append(row);
  }
  document.getElementById("part-count").textContent=`${data.r1.parts.length} verified digital solids`;
  document.getElementById("digital-count").textContent=data.r1.parts.length;
  for(const candidate of data.study.candidates){
    const row=element("tr",null),name=element("td",candidate.name),coverage=element("td",candidate.coverage),next=element("td",candidate.next),state=element("td",null);
    state.append(element("span",candidate.status,{class:"state"}));row.append(name,coverage,next,state);
    document.getElementById("candidate-table").append(row);
  }
  const ns="http://www.w3.org/2000/svg",plot=document.getElementById("result-plot");
  function svg(name,attributes,text){
    const node=document.createElementNS(ns,name);
    for(const [key,value] of Object.entries(attributes))node.setAttribute(key,String(value));
    if(text!==undefined)node.textContent=text;plot.append(node);return node;
  }
  function axes(maximum=20){
    plot.replaceChildren();svg("rect",{width:650,height:360,fill:"#fff"});
    for(let i=0;i<=4;i++){
      const x=60+i*135,y=305-i*66;
      svg("line",{x1:60,y1:y,x2:600,y2:y,stroke:"#e4e9e3"});
      svg("line",{x1:x,y1:41,x2:x,y2:305,stroke:"#e4e9e3"});
      svg("text",{x,y:325,"font-size":11,"text-anchor":"middle",fill:"#536870"},(maximum*i/4).toFixed(1));
      svg("text",{x:48,y:y+4,"font-size":11,"text-anchor":"end",fill:"#536870"},(maximum*i/4).toFixed(1));
    }
    svg("line",{x1:60,y1:305,x2:600,y2:41,stroke:"#aab8ad","stroke-dasharray":"4 4"});
    svg("text",{x:315,y:348,"text-anchor":"middle","font-size":12,fill:"#536870"},"Reference force (N)");
    svg("text",{x:20,y:25,"font-size":12,fill:"#536870"},"Predicted force (N)");
  }
  axes();
  svg("text",{x:330,y:175,"text-anchor":"middle","font-size":15,fill:"#6b7f77"},"Awaiting measured data");
  function renderReport(report,name="imported report"){
    if(report.schema!=="yam-calibration/1"||report.evidence_kind!=="physical"||!Array.isArray(report.channels)){
      throw Error("Expected a physical yam-calibration/1 report from the bench analyzer.");
    }
    const points=[];
    for(const channel of report.channels){
      if(!Number.isInteger(channel.channel)||channel.channel<0||channel.channel>5)throw Error("Invalid channel identifier.");
      for(const point of channel.predictions||[]){
        if(!Number.isFinite(point.reference_n)||point.reference_n<0||point.reference_n>100)throw Error("Invalid reference force.");
        if(point.predicted_n!==null&&(!Number.isFinite(point.predicted_n)||Math.abs(point.predicted_n)>100))throw Error("Invalid predicted force.");
        points.push({...point,channel:channel.channel});
      }
    }
    if(!points.length)throw Error("No held-out predictions in this report.");
    const extent=Math.max(20,...points.map(p=>p.reference_n),...points.filter(p=>p.predicted_n!==null).map(p=>p.predicted_n));
    axes(extent);
    const colors=["#c66d31","#aa7825","#268479","#2f6987","#74a04a","#907ca8"];
    let errors=[],out=0;
    for(const point of points){
      if(point.predicted_n===null){out++;continue;}
      errors.push(point.predicted_n-point.reference_n);
      const dot=svg("circle",{cx:60+540*point.reference_n/extent,cy:305-264*point.predicted_n/extent,r:4,fill:colors[point.channel],opacity:.8});
      const title=document.createElementNS(ns,"title");title.textContent=`CH${point.channel}: reference ${point.reference_n.toFixed(3)} N, prediction ${point.predicted_n.toFixed(3)} N`;dot.append(title);
    }
    const rmse=errors.length?Math.sqrt(errors.reduce((s,e)=>s+e*e,0)/errors.length):null;
    document.getElementById("result-status").textContent=`Locally inspected: ${name}. Published specimen count remains unchanged.`;
    document.getElementById("result-metrics").textContent=`${points.length} held-out trials · ${out} out of range · RMSE of in-range trials: ${rmse===null?"unavailable":rmse.toFixed(3)+" N"}. Static report only; provenance and raw data require review.`;
    plot.dataset.loaded="true";
  }
  document.getElementById("result-file").addEventListener("change",async e=>{
    const file=e.target.files[0];if(!file)return;
    try {
      if(file.size>2*1024*1024)throw Error("Report exceeds 2 MB.");
      renderReport(JSON.parse(await file.text()),file.name);
    } catch(error){document.getElementById("result-status").textContent=error.message;}
  });
  window.EngineeringUI={viewer,renderReport};
})();
