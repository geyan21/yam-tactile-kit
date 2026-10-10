const fs=require("node:fs");
const model=require("../web/model.js");
const cases=JSON.parse(fs.readFileSync(0,"utf8"));
process.stdout.write(JSON.stringify(cases.map(input=>{
  try{return {valid:true,result:model.evaluate(input)};}
  catch(error){return {valid:false};}
})));
