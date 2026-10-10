const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const model = require("../web/model.js");
const example = JSON.parse(fs.readFileSync(path.join(__dirname,"../examples/design.example.json"),"utf8"));

test("default pad, stiffness, and normal-force budgets",()=>{
  const r=model.evaluate(example);
  assert.equal(r.taxels,16);
  assert.equal(r.electrode_nets,10);
  assert.equal(r.minimum_adapter_stiffness_n_per_mm,400);
  assert.equal(r.recovered_normal_force_n,5);
  assert.equal(r.hardware_validated,false);
});
test("contact position and end moment do not alter the ideal force difference",()=>{
  for(const contact_distance_mm of [15,30,55,60]) for(const end_moment_nmm of [-90,0,130]) {
    assert.ok(Math.abs(model.evaluate({...example,contact_distance_mm,end_moment_nmm}).recovered_normal_force_n-5)<1e-10);
  }
});
test("invalid input and zero-cell layouts cannot appear as a successful fit",()=>{
  assert.equal(model.evaluate({...example,face_width_mm:3}).taxels,0);
  for(const change of [{friction_coefficient:0},{applied_force_n:NaN},{cell_pitch_mm:true},{contact_distance_mm:10}]) {
    assert.throws(()=>model.validate({...example,...change}));
  }
});
