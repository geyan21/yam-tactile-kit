/* Browser/CommonJS counterpart of the documented, explicit-unit design model. */
(function (root) {
  "use strict";
  const ranges = {
    finger_length_mm:[10,300], face_width_mm:[1,80], nose_thickness_mm:[0.1,30],
    body_thickness_mm:[0.2,60], pad_length_mm:[1,250], pad_border_mm:[0,10],
    cell_pitch_mm:[0.25,10], pad_stack_mm:[0,10], pad_recess_mm:[0,10],
    sensor_force_n:[0.01,1000], allowed_adapter_deflection_mm:[0.001,5],
    station_spacing_mm:[0.1,100], contact_distance_mm:[0.2,300],
    applied_force_n:[0,1000], end_moment_nmm:[-10000,10000],
    mass_kg:[0,100], friction_coefficient:[0.01,2], static_load_factor:[1,10]
  };
  function validate(d) {
    if (!d || typeof d !== "object" || Array.isArray(d)) throw new Error("Design must be a JSON object");
    if (d.schema_version !== 1) throw new Error("schema_version must be 1");
    if (!["illustrative","measured_inputs"].includes(d.geometry_status)) throw new Error("geometry_status must be illustrative or measured_inputs");
    if (typeof d.label !== "string" || !d.label.trim() || d.label.length > 100) throw new Error("label must be 1–100 characters");
    const v = {schema_version:1,label:d.label,geometry_status:d.geometry_status};
    for (const [key,[low,high]] of Object.entries(ranges)) {
      if (typeof d[key] !== "number" || !Number.isFinite(d[key]) || d[key] < low || d[key] > high) throw new Error(`${key} must be finite and between ${low} and ${high}`);
      v[key] = d[key];
    }
    if (v.nose_thickness_mm > v.body_thickness_mm) throw new Error("Nose thickness cannot exceed body thickness");
    if (v.pad_length_mm > v.finger_length_mm) throw new Error("Pad length cannot exceed finger length");
    if (!(v.station_spacing_mm < v.contact_distance_mm && v.contact_distance_mm <= v.finger_length_mm)) throw new Error("Contact must lie beyond both stations and within finger length");
    if (v.pad_recess_mm >= v.body_thickness_mm) throw new Error("Pad recess must be less than body thickness");
    return v;
  }
  function evaluate(input) {
    const d = validate(input);
    let columns = Math.floor((Math.max(0,d.face_width_mm-2*d.pad_border_mm)+1e-10)/d.cell_pitch_mm);
    let rows = Math.floor((Math.max(0,d.pad_length_mm-2*d.pad_border_mm)+1e-10)/d.cell_pitch_mm);
    if (columns*rows === 0) columns = rows = 0;
    const m1 = d.applied_force_n*d.contact_distance_mm+d.end_moment_nmm;
    const m2 = d.applied_force_n*(d.contact_distance_mm-d.station_spacing_mm)+d.end_moment_nmm;
    const required = d.mass_kg*9.80665*d.static_load_factor/(2*d.friction_coefficient);
    const issues = [];
    if (!columns) issues.push("No full sensing cell fits after the assumed borders.");
    if (d.applied_force_n > d.sensor_force_n) issues.push("Applied force exceeds the entered sensor range.");
    if (required > d.sensor_force_n) issues.push("Static support estimate exceeds the entered per-jaw sensor range.");
    if (columns > 16 || rows > 32) issues.push("Layout exceeds the cited 16-column × 32-row example scanner envelope.");
    return {
      schema_version:1, geometry_status:d.geometry_status, hardware_validated:false,
      columns, rows, taxels:columns*rows, electrode_nets:columns ? columns+rows : 0,
      active_width_mm:columns*d.cell_pitch_mm, active_length_mm:rows*d.cell_pitch_mm,
      opening_loss_mm:2*Math.max(0,d.pad_stack_mm-d.pad_recess_mm),
      minimum_adapter_stiffness_n_per_mm:d.sensor_force_n/d.allowed_adapter_deflection_mm,
      required_static_force_per_jaw_n:required, moment_1_nmm:m1, moment_2_nmm:m2,
      recovered_normal_force_n:(m1-m2)/d.station_spacing_mm,
      single_station_fixed_lever_force_n:m1/d.finger_length_mm,
      force_range_remaining_n:d.sensor_force_n-required, issues,
      scope:"Envelope arithmetic and ideal static force balance; not CAD fit, FEA, sensor accuracy, or an actuator guarantee."
    };
  }
  const api = Object.freeze({ranges,validate,evaluate});
  root.TactileModel = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis !== "undefined" ? globalThis : window);
