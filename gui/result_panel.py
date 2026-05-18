"""
結果表示パネル

上段: 主要指標 (Q_total, ε, 平均ΔT, 水出口温度, h値, UA)
下段: 3チャート
  - 左:  空気出口温度の行分布 (最終コラム棒グラフ)
  - 中:  各パスの水温プロファイル (管順序 vs 水温)
  - 右:  局所熱交換量 Q_cell ヒートマップ
"""

from __future__ import annotations

import numpy as np
import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt
import matplotlib.gridspec as mgridspec
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QGroupBox, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt

from domain.fluid import WaterInlet, AirCondition
from domain.pass_config import PassConfiguration
from domain.solver import SolverResult


class MetricLabel(QFrame):
    """ラベル + 値を縦に並べたシンプルな表示ウィジェット"""
    def __init__(self, title: str, unit: str = "") -> None:
        super().__init__()
        self.setFrameShape(QFrame.Shape.Box)
        self.setFrameShadow(QFrame.Shadow.Sunken)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)

        self._title = QLabel(title)
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setStyleSheet("color: gray; font-size: 10px;")
        self._title.setWordWrap(True)

        self._val = QLabel("—")
        self._val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._val.setStyleSheet("font-size: 15px; font-weight: bold;")

        self._unit = QLabel(unit)
        self._unit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._unit.setStyleSheet("color: gray; font-size: 10px;")

        layout.addWidget(self._title)
        layout.addWidget(self._val)
        layout.addWidget(self._unit)

        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_value(self, text: str) -> None:
        self._val.setText(text)


class ResultPanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        # ---- 上段: 主要指標 -----------------------------------------------
        metrics_frame = QGroupBox("計算結果")
        grid = QGridLayout(metrics_frame)
        grid.setSpacing(4)

        self.m_Q      = MetricLabel("総熱交換量",       "kW")
        self.m_eps    = MetricLabel("効率 ε",            "")
        self.m_dT_air = MetricLabel("空気ΔT (平均)",    "°C")
        self.m_Tw_out = MetricLabel("水出口温度 (最終)", "°C")
        self.m_h_air  = MetricLabel("h_air",            "W/m²K")
        self.m_h_w    = MetricLabel("h_water",          "W/m²K")
        self.m_UA     = MetricLabel("UA (1セル)",        "W/K")

        for col, m in enumerate([
            self.m_Q, self.m_eps, self.m_dT_air, self.m_Tw_out,
            self.m_h_air, self.m_h_w, self.m_UA,
        ]):
            grid.addWidget(m, 0, col)

        layout.addWidget(metrics_frame)

        # ---- 下段: チャート -----------------------------------------------
        self._fig, self._axes = plt.subplots(
            1, 3, figsize=(12, 4),
            gridspec_kw={"wspace": 0.35},
        )
        self._canvas  = FigureCanvasQTAgg(self._fig)
        self._toolbar = NavigationToolbar2QT(self._canvas, self)
        layout.addWidget(self._toolbar)
        layout.addWidget(self._canvas)

        self._placeholder = QLabel("パラメータを設定して ▶ Run を押してください")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: gray; font-size: 14px;")
        layout.addWidget(self._placeholder)

        self._canvas.hide()
        self._toolbar.hide()

    # ------------------------------------------------------------------
    def update_result(
        self,
        result: SolverResult,
        water_inlet: WaterInlet,
        air_cond: AirCondition,
        pass_cfg: PassConfiguration,
    ) -> None:
        # 主要指標の更新
        T_last_col = result.T_air_out[:, -1]
        dT_mean = float(np.mean(T_last_col)) - air_cond.T_in

        # 全パスの最後の出口水温 (直列最終パス or 並列平均)
        T_w_final = float(np.mean(list(result.T_water_out_per_pass.values())))

        self.m_Q.set_value(f"{result.Q_total/1000:.2f}")
        self.m_eps.set_value(f"{result.effectiveness:.4f}")
        self.m_dT_air.set_value(f"+{dT_mean:.2f}")
        self.m_Tw_out.set_value(f"{T_w_final:.2f}")
        self.m_h_air.set_value(f"{result.h_air_val:.1f}")
        self.m_h_w.set_value(f"{result.h_water_val:.1f}")
        self.m_UA.set_value(f"{result.UA_cell:.3f}")

        # チャート描画
        self._placeholder.hide()
        self._canvas.show()
        self._toolbar.show()

        for ax in self._axes:
            ax.clear()

        self._draw_air_outlet(self._axes[0], result, air_cond)
        self._draw_water_profile(self._axes[1], result, pass_cfg, water_inlet)
        self._draw_q_heatmap(self._axes[2], result)

        self._fig.tight_layout()
        self._canvas.draw()

    # ------------------------------------------------------------------
    def _draw_air_outlet(self, ax, result: SolverResult, air_cond: AirCondition) -> None:
        """空気出口温度の行分布 (最終コラム)"""
        T_out = result.T_air_out[:, -1]
        rows = np.arange(len(T_out))
        ax.barh(rows, T_out, color="tomato", alpha=0.8, label="T_air_out")
        ax.axvline(air_cond.T_in, color="steelblue", ls="--", lw=1, label="T_in")
        ax.set_xlabel("空気温度 [°C]", fontsize=8)
        ax.set_ylabel("row", fontsize=8)
        ax.set_title("空気出口温度分布\n(最終コラム)", fontsize=9)
        ax.legend(fontsize=7)
        ax.tick_params(labelsize=7)

    def _draw_water_profile(
        self, ax, result: SolverResult, pass_cfg: PassConfiguration, water_inlet: WaterInlet
    ) -> None:
        """各パスの水温プロファイル (管順序 vs 水温)"""
        colors = plt.cm.tab10.colors  # type: ignore[attr-defined]
        T_water_grid = result.T_water_grid

        for p in pass_cfg.sorted_passes():
            seq = p.tube_sequence
            T_seq = [water_inlet.T_in] + [
                T_water_grid[row, col] for (row, col) in seq
            ]
            xs = list(range(len(T_seq)))
            c = colors[p.pass_id % len(colors)]
            ax.plot(xs, T_seq, marker="o", markersize=3, lw=1.2,
                    color=c, label=f"Pass {p.pass_id}")

        ax.set_xlabel("管順序 (シーケンス番号)", fontsize=8)
        ax.set_ylabel("水温 [°C]", fontsize=8)
        ax.set_title("水温プロファイル\n(各パス)", fontsize=9)
        ax.legend(fontsize=7)
        ax.tick_params(labelsize=7)

    def _draw_q_heatmap(self, ax, result: SolverResult) -> None:
        """局所熱交換量 Q_cell ヒートマップ"""
        Q = result.Q_cell  # [n_rows, n_cols]
        im = ax.imshow(
            Q, aspect="auto", origin="upper",
            cmap="YlOrRd", interpolation="nearest",
        )
        self._fig.colorbar(im, ax=ax, label="Q [W]", fraction=0.046, pad=0.04)
        ax.set_xlabel("コラム (col)", fontsize=8)
        ax.set_ylabel("行 (row)", fontsize=8)
        ax.set_title("局所熱交換量\nQ_cell [W]", fontsize=9)
        ax.tick_params(labelsize=7)
