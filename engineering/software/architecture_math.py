"""Analytical exploration only. These functions do not decode a robot force sensor."""

import math


def beam_response(config, force_n, arm_mm, end_moment_nmm=0.0):
    """Euler-Bernoulli constant-section beam, rigid end clamps and rigid distal arm."""
    b=config["beam_width_mm"];h=config["beam_thickness_mm"];length=config["active_length_mm"]
    modulus=config["youngs_modulus_mpa_assumed"]
    x1,x2=config["gauge_station_mm_from_fixed_boundary"]
    if min(b,h,length,modulus)<=0 or not 0<x1<x2<length or arm_mm<0:
        raise ValueError("Invalid constant-section beam geometry")
    inertia=b*h**3/12
    applied_moment=force_n*arm_mm+end_moment_nmm
    moments=[applied_moment+force_n*(length-x) for x in (x1,x2)]
    strain=[moment*h/(2*modulus*inertia) for moment in moments]
    full_bridge=[config["excitation_v"]*config["gauge_factor_assumed"]*value for value in strain]
    delta_strain=strain[0]-strain[1]
    rotation=(force_n*length**2/2+applied_moment*length)/(modulus*inertia)
    end_displacement=(force_n*length**3/3+applied_moment*length**2/2)/(modulus*inertia)
    sensitivity=config["excitation_v"]*config["gauge_factor_assumed"]*6*(x2-x1)/(modulus*b*h*h)
    rms_v=math.sqrt(2)*config["adc_short_input_typical_rms_nv_at_5v"]*1e-9
    return {
        "force_n":force_n,"contact_arm_mm":arm_mm,"applied_end_moment_nmm":applied_moment,
        "station_moments_nmm":moments,"station_strain":strain,
        "bridge_v_ideal":full_bridge,"difference_strain":delta_strain,
        "difference_v_ideal":full_bridge[0]-full_bridge[1],
        "sensitivity_v_per_n":sensitivity,
        "recovered_force_ideal_n":(full_bridge[0]-full_bridge[1])/sensitivity,
        "rotation_rad":rotation,"added_contact_displacement_mm":end_displacement+arm_mm*rotation,
        "active_beam_max_bending_stress_mpa":abs((applied_moment+force_n*length)*h/(2*inertia)),
        "adc_only_force_equivalent_rms_n":rms_v/sensitivity,
        "note":"Ideal small-deflection model. ADC-only RMS is not sensor resolution, accuracy or a contact threshold."
    }


def force_with_station_gain_error(response, relative_error):
    return (response["bridge_v_ideal"][0]*(1+relative_error)-response["bridge_v_ideal"][1])/response["sensitivity_v_per_n"]


def batch_cost(good_units, unit_parts, yield_fraction, labor_minutes, hourly_rate,
               fixed_setup=0, calibration_minutes=0):
    """Quote calculator; values are supplied by the operator, never invented market prices."""
    inputs=(good_units,unit_parts,yield_fraction,labor_minutes,hourly_rate,fixed_setup,calibration_minutes)
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in inputs):
        raise ValueError("Finite numerical quote inputs required")
    if good_units<=0 or unit_parts<0 or not 0<yield_fraction<=1 or min(labor_minutes,hourly_rate,fixed_setup,calibration_minutes)<0:
        raise ValueError("Invalid cost or yield")
    attempted=math.ceil(good_units/yield_fraction)
    cost=fixed_setup+attempted*(unit_parts+(labor_minutes+calibration_minutes)*hourly_rate/60)
    return {"requested_good_units":good_units,"attempted_units":attempted,
            "modeled_total":cost,"modeled_per_good_unit":cost/good_units,
            "basis":"Operator-entered quote/yield assumptions; not a purchase quote or measured production result"}
