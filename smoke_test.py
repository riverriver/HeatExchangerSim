# -*- coding: utf-8 -*-
"""
Phase 1 smoke test
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from domain.geometry import TubeGeometry, FinGeometry
from domain.fluid import FluidProperties, WaterInlet, AirCondition, AIR, WATER
from domain.pass_config import make_serpentine, make_parallel_passes, make_series_passes, PassConfiguration, Pass
from domain.solver import run, SolverConfig, LateralMixingMode
import numpy as np


def print_result(label, result):
    print(f"\n{'='*52}")
    print(f"  {label}")
    print(f"{'='*52}")
    print(f"  Q_total       : {result.Q_total/1000:.3f} kW")
    print(f"  Effectiveness : {result.effectiveness:.4f}")
    print(f"  UA_cell       : {result.UA_cell:.4f} W/K")
    print(f"  h_air         : {result.h_air_val:.2f} W/m2K")
    print(f"  h_water       : {result.h_water_val:.2f} W/m2K")
    print(f"  Air outlet temps (final col) [C]:")
    for row in range(result.T_air_out.shape[0]):
        print(f"    row={row}: {result.T_air_out[row, -1]:.2f}")
    print(f"  Air outlet mean: {result.T_air_out_mean:.2f} C")
    print(f"  Water outlet (per pass):")
    for pid, T in result.T_water_out_per_pass.items():
        print(f"    pass {pid}: {T:.2f} C")


tube = TubeGeometry(
    do=0.010, di=0.008, length=0.5,
    Sl=0.025, St=0.025,
    n_rows=4, n_cols=4,
    arrangement="staggered",
)
fin  = FinGeometry(pitch=0.002, thickness=0.0001, k_fin=205.0)
air_cond    = AirCondition(T_in=25.0, velocity=2.0)
water_inlet = WaterInlet(T_in=60.0, flow_rate=0.1)


# Test 1: serpentine, staggered, STREAM
pc1 = make_serpentine(tube.n_rows, tube.n_cols)
r1  = run(tube, fin, AIR, WATER, air_cond, water_inlet, pc1)
print_result("Serpentine / Staggered / STREAM", r1)

# Test 2: same with SIMPLE
r2 = run(tube, fin, AIR, WATER, air_cond, water_inlet, pc1,
         SolverConfig(mixing_mode=LateralMixingMode.SIMPLE))
print_result("Serpentine / Staggered / SIMPLE", r2)
print(f"\n  STREAM-SIMPLE dQ = {(r1.Q_total-r2.Q_total)/1000:.4f} kW")
print(f"  STREAM-SIMPLE dTair_mean = {r1.T_air_out_mean-r2.T_air_out_mean:.4f} C")

# Test 3: 2 parallel passes
pc3 = make_parallel_passes(tube.n_rows, tube.n_cols, 2)
r3  = run(tube, fin, AIR, WATER, air_cond, water_inlet, pc3)
print_result("2 Parallel / Staggered / STREAM", r3)

# Test 4: inline (no mixing)
tube_il = TubeGeometry(
    do=tube.do, di=tube.di, length=tube.length,
    Sl=tube.Sl, St=tube.St,
    n_rows=tube.n_rows, n_cols=tube.n_cols,
    arrangement="inline",
)
pc4 = make_serpentine(tube_il.n_rows, tube_il.n_cols)
r4  = run(tube_il, fin, AIR, WATER, air_cond, water_inlet, pc4)
print_result("Serpentine / Inline / NONE", r4)

# Test 5: series 2 passes
pc5 = make_series_passes(tube.n_rows, tube.n_cols)
r5  = run(tube, fin, AIR, WATER, air_cond, water_inlet, pc5)
print_result("Series 2-pass / Staggered", r5)

print("\n\nAll tests done.")
