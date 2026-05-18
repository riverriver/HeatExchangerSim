"""
メインソルバー: セル毎ε-NTU差分法 (列優先ループ)

アルゴリズム:
1. 定物性でセルUAを事前計算
2. 空気温度行列を初期化 (一様入口)
3. 列 col=0,1,...,nc-1 を左から順に処理
   a. その列に管を持つ全パスの管をその列内で処理
   b. パスの水温を管順序に従い更新
   c. T_air_grid[row, col+1] を書き込む
   d. 列の全管が処理済みになったら横方向混合を適用
4. 直列パスは前段パスの全列処理完了後に水温を引き継ぐ
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
import math
import numpy as np

from .geometry import TubeGeometry, FinGeometry
from .fluid import FluidProperties, WaterInlet, AirCondition
from .pass_config import PassConfiguration, Pass
from .correlations import cell_UA, h_air as _h_air, h_water as _h_water


class LateralMixingMode(Enum):
    NONE   = "none"    # 正方配列用 (混合なし)
    SIMPLE = "simple"  # Approach A: 加重平均 (α=0.6, β=0.4)
    STREAM = "stream"  # Approach B: ストリーム分割 (デフォルト)


@dataclass
class SolverConfig:
    mixing_mode: LateralMixingMode = LateralMixingMode.STREAM
    simple_alpha: float = 0.6  # SIMPLE モード用 α


@dataclass
class SolverResult:
    Q_total: float
    effectiveness: float
    T_air_out: np.ndarray           # [n_rows, n_cols]  各セル出口空気温度 [°C]
    T_water_grid: np.ndarray        # [n_rows, n_cols]  各管出口水温 [°C]
    T_water_out_per_pass: dict[int, float]
    Q_cell: np.ndarray              # [n_rows, n_cols]  局所熱交換量 [W]
    UA_cell: float
    h_air_val: float
    h_water_val: float

    @property
    def T_air_out_mean(self) -> float:
        """最終コラムの空気出口温度の行平均"""
        return float(np.mean(self.T_air_out[:, -1]))


# ---------------------------------------------------------------------------
# セル単位の熱計算 (ε-NTU, 直交流・両流体非混合)
# ---------------------------------------------------------------------------

def _solve_cell(
    T_air_in: float,
    T_water_in: float,
    UA: float,
    C_air: float,
    C_water: float,
) -> tuple[float, float, float]:
    """Returns: T_air_out, T_water_out, Q  [°C, °C, W]"""
    if T_water_in <= T_air_in:
        return T_air_in, T_water_in, 0.0

    C_min = min(C_air, C_water)
    C_max = max(C_air, C_water)
    C_r   = C_min / C_max
    NTU   = UA / C_min

    # 直交流・両流体非混合 (Incropera式)
    eps = 1.0 - math.exp(
        (NTU ** 0.22 / C_r) * (math.exp(-C_r * NTU ** 0.78) - 1.0)
    )
    eps = min(max(eps, 0.0), 1.0)

    Q           = eps * C_min * (T_water_in - T_air_in)
    T_air_out   = T_air_in   + Q / C_air
    T_water_out = T_water_in - Q / C_water
    return T_air_out, T_water_out, Q


# ---------------------------------------------------------------------------
# 横方向混合
# ---------------------------------------------------------------------------

def _apply_lateral_mixing(
    T_col: np.ndarray,
    col_index: int,
    mode: LateralMixingMode,
    alpha: float = 0.6,
) -> np.ndarray:
    """
    コラム col_index を通過後の空気温度列 T_col[n_rows] に
    横方向混合を適用し、次コラムへの入口温度列を返す。
    """
    if mode == LateralMixingMode.NONE:
        return T_col.copy()

    n = len(T_col)
    T_next = np.empty(n)

    if mode == LateralMixingMode.SIMPLE:
        beta = 1.0 - alpha
        T_next[0]   = alpha * T_col[0]   + beta * T_col[1]
        T_next[n-1] = alpha * T_col[n-1] + beta * T_col[n-2]
        for j in range(1, n - 1):
            T_next[j] = alpha * T_col[j] + beta * 0.5 * (T_col[j-1] + T_col[j+1])

    elif mode == LateralMixingMode.STREAM:
        # 偶→奇: 管が下に半ピッチ移動 → j と j+1 の平均が次コラムの j に流入
        # 奇→偶: 管が上に半ピッチ移動 → j-1 と j の平均が次コラムの j に流入
        if col_index % 2 == 0:
            for j in range(n - 1):
                T_next[j] = 0.5 * (T_col[j] + T_col[j + 1])
            T_next[n - 1] = T_col[n - 1]       # 下端境界
        else:
            T_next[0] = T_col[0]                 # 上端境界
            for j in range(1, n):
                T_next[j] = 0.5 * (T_col[j - 1] + T_col[j])

    return T_next


# ---------------------------------------------------------------------------
# メインソルバー
# ---------------------------------------------------------------------------

def run(
    tube: TubeGeometry,
    fin: FinGeometry,
    air_prop: FluidProperties,
    water_prop: FluidProperties,
    air_cond: AirCondition,
    water_inlet: WaterInlet,
    pass_config: PassConfiguration,
    solver_cfg: SolverConfig | None = None,
) -> SolverResult:
    if solver_cfg is None:
        solver_cfg = SolverConfig()

    nr = tube.n_rows
    nc = tube.n_cols

    # ------------------------------------------------------------------
    # 流量分配・代表流量
    # ------------------------------------------------------------------
    flow_per_pass = pass_config.flow_rate_per_pass(water_inlet.flow_rate)
    n_parallel_roots = sum(1 for p in pass_config.passes if p.inlet_source is None)
    flow_repr = water_inlet.flow_rate / n_parallel_roots

    # ------------------------------------------------------------------
    # 事前計算 (定物性なので1回のみ)
    # ------------------------------------------------------------------
    UA = cell_UA(tube, fin, air_prop, water_prop, air_cond.velocity, flow_repr)

    rho_u      = air_prop.rho * air_cond.velocity
    m_dot_air  = rho_u * tube.St * tube.length
    C_air_cell = m_dot_air * air_prop.cp

    C_water_total = water_inlet.flow_rate * water_prop.cp
    C_air_total   = rho_u * (tube.St * nr) * tube.length * air_prop.cp
    Q_max = min(C_water_total, C_air_total) * (water_inlet.T_in - air_cond.T_in)

    # ------------------------------------------------------------------
    # 管インデックス → (パス, パス内シーケンス番号) のマッピング
    # ------------------------------------------------------------------
    # {(row, col): (pass_id, seq_idx)}
    tube_map: dict[tuple[int, int], tuple[int, int]] = {}
    for p in pass_config.passes:
        for seq_idx, idx in enumerate(p.tube_sequence):
            tube_map[idx] = (p.pass_id, seq_idx)

    pass_by_id: dict[int, Pass] = {p.pass_id: p for p in pass_config.passes}

    # ------------------------------------------------------------------
    # 状態変数の初期化
    # ------------------------------------------------------------------
    # T_air_grid[row, col]: col コラムへの入口空気温度
    # col=0 が入口 (一様)、col=nc が出口
    T_air_grid = np.full((nr, nc + 1), air_cond.T_in)

    Q_cell        = np.zeros((nr, nc))
    T_water_grid  = np.full((nr, nc), water_inlet.T_in)
    T_water_state: dict[int, float] = {}   # pass_id → 現在の水温
    pass_initialized: set[int] = set()     # 初期化済みパスID
    T_water_out_per_pass: dict[int, float] = {}

    sorted_passes = pass_config.sorted_passes()

    def init_pass_if_needed(p: Pass) -> bool:
        """パスを初期化する。直列依存がある場合、前段パスの完了を待つ。
        初期化できた場合 True、まだ前段が未完了の場合 False を返す。"""
        if p.pass_id in pass_initialized:
            return True
        if p.inlet_source is None:
            T_water_state[p.pass_id] = water_inlet.T_in
            pass_initialized.add(p.pass_id)
            return True
        src = p.inlet_source
        if src not in T_water_out_per_pass:
            # 前段パスがまだ完了していない → 初期化を延期
            return False
        T_water_state[p.pass_id] = T_water_out_per_pass[src]
        pass_initialized.add(p.pass_id)
        return True

    # ------------------------------------------------------------------
    # 列優先ループ: col=0 から nc-1 まで左から処理
    # ------------------------------------------------------------------
    # 各パスの「次に処理すべきシーケンスインデックス」を追跡
    pass_seq_ptr: dict[int, int] = {p.pass_id: 0 for p in pass_config.passes}

    for col in range(nc):
        # このコラムの管を持つパスを解析順に処理
        for p in sorted_passes:
            if not init_pass_if_needed(p):
                continue  # 前段パスがまだ未完了 → スキップ
            m_dot_w  = flow_per_pass[p.pass_id]
            C_water  = m_dot_w * water_prop.cp

            # このパスのこのコラムにある管を順番に処理
            ptr = pass_seq_ptr[p.pass_id]
            seq = p.tube_sequence

            # シーケンス内でこのコラムに属する管を連続して処理
            while ptr < len(seq) and seq[ptr][1] == col:
                row = seq[ptr][0]
                T_air_out, T_w_out, Q = _solve_cell(
                    T_air_grid[row, col],
                    T_water_state[p.pass_id],
                    UA,
                    C_air_cell,
                    C_water,
                )
                T_air_grid[row, col + 1] = T_air_out
                Q_cell[row, col]         = Q
                T_water_grid[row, col]   = T_w_out
                T_water_state[p.pass_id] = T_w_out
                ptr += 1

            pass_seq_ptr[p.pass_id] = ptr

            # このパスの全管を処理し終えた場合、出口水温を確定
            if ptr == len(seq):
                T_water_out_per_pass[p.pass_id] = T_water_state[p.pass_id]

        # このコラムが全パスで処理済みなら横方向混合を適用
        if tube.arrangement == "staggered":
            mixing = solver_cfg.mixing_mode
            T_air_grid[:, col + 1] = _apply_lateral_mixing(
                T_air_grid[:, col + 1],
                col,
                mixing,
                solver_cfg.simple_alpha,
            )

    # パスのうち出口未確定のものを確定 (全管が最終列まで処理済みのはず)
    for p in pass_config.passes:
        if p.pass_id not in T_water_out_per_pass:
            T_water_out_per_pass[p.pass_id] = T_water_state.get(p.pass_id, water_inlet.T_in)

    # ------------------------------------------------------------------
    # 集計
    # ------------------------------------------------------------------
    Q_total      = float(Q_cell.sum())
    effectiveness = Q_total / Q_max if Q_max > 0 else 0.0

    h_a = _h_air(tube, fin, air_prop, air_cond.velocity)
    h_w = _h_water(tube, water_prop, flow_repr)

    return SolverResult(
        Q_total=Q_total,
        effectiveness=effectiveness,
        T_air_out=T_air_grid[:, 1:],
        T_water_grid=T_water_grid,
        T_water_out_per_pass=T_water_out_per_pass,
        Q_cell=Q_cell,
        UA_cell=UA,
        h_air_val=h_a,
        h_water_val=h_w,
    )
