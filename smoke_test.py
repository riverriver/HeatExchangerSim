"""
Phase 1 スモークテスト
典型的な水-空気熱交換器で計算を走らせ、結果を確認する。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from domain.geometry import TubeGeometry, FinGeometry
from domain.fluid import FluidProperties, WaterInlet, AirCondition, AIR, WATER
from domain.pass_config import make_serpentine, make_parallel_passes, PassConfiguration, Pass
from domain.solver import run, SolverConfig, LateralMixingMode
import numpy as np


def print_result(label, result):
    print(f"\n{'='*50}")
    print(f"  {label}")
    print(f"{'='*50}")
    print(f"  Q_total       : {result.Q_total/1000:.3f} kW")
    print(f"  Effectiveness : {result.effectiveness:.4f}")
    print(f"  UA_cell       : {result.UA_cell:.4f} W/K")
    print(f"  h_air         : {result.h_air_val:.2f} W/m²K")
    print(f"  h_water       : {result.h_water_val:.2f} W/m²K")
    print(f"  空気出口温度 (各行, 最終列) [°C]:")
    for row in range(result.T_air_out.shape[0]):
        print(f"    row={row}: {result.T_air_out[row, -1]:.2f}")
    print(f"  空気出口温度 平均: {result.T_air_out_mean:.2f} °C")
    print(f"  水出口温度 (per pass):")
    for pid, T in result.T_water_out_per_pass.items():
        print(f"    pass {pid}: {T:.2f} °C")


# ------------------------------------------------------------------
# 共通形状設定
# ------------------------------------------------------------------
tube = TubeGeometry(
    do=0.010,       # 外径 10mm
    di=0.008,       # 内径 8mm
    length=0.5,     # 管長 500mm
    Sl=0.025,       # 縦ピッチ 25mm
    St=0.025,       # 横ピッチ 25mm
    n_rows=4,       # 4段
    n_cols=4,       # 4列
    arrangement="staggered",
)

fin = FinGeometry(
    pitch=0.002,     # フィンピッチ 2mm
    thickness=0.0001, # フィン厚さ 0.1mm
    k_fin=205.0,     # アルミ
)

air_cond = AirCondition(T_in=25.0, velocity=2.0)
water_inlet = WaterInlet(T_in=60.0, flow_rate=0.1)


# ------------------------------------------------------------------
# テスト1: 蛇行1パス (千鳥, STREAMモード)
# ------------------------------------------------------------------
pc_serpentine = make_serpentine(tube.n_rows, tube.n_cols)
result1 = run(tube, fin, AIR, WATER, air_cond, water_inlet, pc_serpentine)
print_result("蛇行1パス / 千鳥 / STREAM混合", result1)


# ------------------------------------------------------------------
# テスト2: 同条件でSIMPLEモードと比較
# ------------------------------------------------------------------
cfg_simple = SolverConfig(mixing_mode=LateralMixingMode.SIMPLE)
result2 = run(tube, fin, AIR, WATER, air_cond, water_inlet, pc_serpentine, cfg_simple)
print_result("蛇行1パス / 千鳥 / SIMPLE混合", result2)

print(f"\n  STREAM vs SIMPLE Q差: {(result1.Q_total - result2.Q_total)/1000:.4f} kW")
print(f"  STREAM vs SIMPLE 空気平均温度差: "
      f"{result1.T_air_out_mean - result2.T_air_out_mean:.4f} °C")


# ------------------------------------------------------------------
# テスト3: 2並列パス (千鳥, STREAMモード)
# ------------------------------------------------------------------
pc_parallel = make_parallel_passes(tube.n_rows, tube.n_cols, n_passes=2)
result3 = run(tube, fin, AIR, WATER, air_cond, water_inlet, pc_parallel)
print_result("2並列パス / 千鳥 / STREAM混合", result3)


# ------------------------------------------------------------------
# テスト4: 正方配列 (混合なし)
# ------------------------------------------------------------------
tube_inline = TubeGeometry(
    do=tube.do, di=tube.di, length=tube.length,
    Sl=tube.Sl, St=tube.St,
    n_rows=tube.n_rows, n_cols=tube.n_cols,
    arrangement="inline",
)
pc_inline = make_serpentine(tube_inline.n_rows, tube_inline.n_cols)
result4 = run(tube_inline, fin, AIR, WATER, air_cond, water_inlet, pc_inline)
print_result("蛇行1パス / 正方配列", result4)


# ------------------------------------------------------------------
# テスト5: 直列パス (パスA → パスB)
# ------------------------------------------------------------------
pc_series = PassConfiguration(passes=[
    Pass(pass_id=0, tube_sequence=[(r, c) for c in range(2) for r in range(4)]),
    Pass(pass_id=1, tube_sequence=[(r, c) for c in range(2, 4) for r in range(4)], inlet_source=0),
])
result5 = run(tube, fin, AIR, WATER, air_cond, water_inlet, pc_series)
print_result("直列2パス (Pass0→Pass1) / 千鳥", result5)

print("\n\n✓ 全テスト完了")
