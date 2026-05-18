"""
熱交換器グリッドビュー

左ペイン: 管配置 + 温度カラーマップ
  - 背景 (pcolormesh): 各セル出口の空気温度分布
  - 円マーカー: 管位置、水温で色付け
  - 千鳥配列では奇数コラムを半ピッチ上にオフセット表示
"""

from __future__ import annotations

import numpy as np
import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.colors import Normalize
from matplotlib.cm import ScalarMappable
from matplotlib.gridspec import GridSpec
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import Qt

from domain.geometry import TubeGeometry
from domain.solver import SolverResult
from domain.pass_config import PassConfiguration


# パス毎の表示色 (最大8パス)
PASS_COLORS = [
    "#2196F3", "#F44336", "#4CAF50", "#FF9800",
    "#9C27B0", "#00BCD4", "#795548", "#607D8B",
]


class GridView(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # placeholder
        self._placeholder = QLabel("パラメータを設定して ▶ Run を押してください")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: gray; font-size: 14px;")
        layout.addWidget(self._placeholder)

        # matplotlib figure (最初は非表示)
        self._fig = plt.figure(figsize=(10, 5), constrained_layout=True)
        self._canvas = FigureCanvasQTAgg(self._fig)
        self._toolbar = NavigationToolbar2QT(self._canvas, self)
        layout.addWidget(self._toolbar)
        layout.addWidget(self._canvas)

        self._canvas.hide()
        self._toolbar.hide()

    # ------------------------------------------------------------------
    def update_result(
        self,
        result: SolverResult,
        tube: TubeGeometry,
        pass_cfg: PassConfiguration,
    ) -> None:
        self._placeholder.hide()
        self._canvas.show()
        self._toolbar.show()

        self._fig.clear()
        gs = GridSpec(
            1, 4,
            figure=self._fig,
            width_ratios=[10, 0.35, 0.35, 0.35],
        )
        ax      = self._fig.add_subplot(gs[0, 0])
        cax_air = self._fig.add_subplot(gs[0, 1])
        cax_w   = self._fig.add_subplot(gs[0, 2])
        cax_q   = self._fig.add_subplot(gs[0, 3])

        self._draw_grid(ax, cax_air, cax_w, cax_q, result, tube, pass_cfg)
        self._canvas.draw()

    # ------------------------------------------------------------------
    def _draw_grid(
        self,
        ax, cax_air, cax_w, cax_q,
        result: SolverResult,
        tube: TubeGeometry,
        pass_cfg: PassConfiguration,
    ) -> None:
        nr = tube.n_rows
        nc = tube.n_cols

        # ---- 背景: 空気出口温度 heatmap ---------------------------------
        # T_air_out[row, col] → 各セルの空気出口温度
        # pcolormesh の x,y はセル境界を指定 (nc+1 点 × nr+1 点)
        T_air = result.T_air_out  # [nr, nc]
        T_air_min = float(np.min(T_air))
        T_air_max = float(np.max(T_air))
        if abs(T_air_max - T_air_min) < 0.01:
            T_air_max = T_air_min + 1.0

        X = np.arange(nc + 1)        # 0..nc
        Y = np.arange(nr + 1)        # 0..nr
        Xg, Yg = np.meshgrid(X, Y)
        norm_air = Normalize(vmin=T_air_min, vmax=T_air_max)
        pm = ax.pcolormesh(
            Xg, Yg, T_air,
            cmap="RdYlBu_r", norm=norm_air,
            shading="flat", alpha=0.6, zorder=1,
        )
        plt.colorbar(pm, cax=cax_air, label="空気出口温度 [°C]")

        # ---- 管: 水温カラー ---------------------------------------------
        T_water = result.T_water_grid  # [nr, nc]
        T_w_min = float(np.min(T_water))
        T_w_max = float(np.max(T_water))
        if abs(T_w_max - T_w_min) < 0.01:
            T_w_max = T_w_min + 1.0
        norm_w = Normalize(vmin=T_w_min, vmax=T_w_max)
        cmap_w = plt.cm.plasma  # type: ignore[attr-defined]

        # 千鳥配列: 奇数コラムは +0.5 y オフセット
        stagger_offset = 0.5 if tube.arrangement == "staggered" else 0.0
        tube_radius_data = 0.35  # データ座標での管半径 (視覚的サイズ)

        for row in range(nr):
            for col in range(nc):
                x_c = col + 0.5
                y_offset = stagger_offset if (col % 2 == 1) else 0.0
                y_c = row + 0.5 + y_offset

                # 管円
                color = cmap_w(norm_w(T_water[row, col]))
                circle = mpatches.Circle(
                    (x_c, y_c), tube_radius_data,
                    facecolor=color, edgecolor="k",
                    linewidth=0.8, zorder=3,
                )
                ax.add_patch(circle)

                # パス番号ラベル (管内に小さく表示)
                ax.text(
                    x_c, y_c, f"{col}",
                    ha="center", va="center",
                    fontsize=5, color="white", zorder=4,
                )

        sm_w = ScalarMappable(norm=norm_w, cmap=cmap_w)
        sm_w.set_array([])
        plt.colorbar(sm_w, cax=cax_w, label="水出口温度 [°C]")

        # ---- 局所熱交換量 -----------------------------------------------
        Q = result.Q_cell  # [nr, nc]
        Q_min, Q_max_val = float(np.min(Q)), float(np.max(Q))
        if abs(Q_max_val - Q_min) < 0.01:
            Q_max_val = Q_min + 1.0
        norm_q = Normalize(vmin=Q_min, vmax=Q_max_val)
        sm_q = ScalarMappable(norm=norm_q, cmap="Greens")
        sm_q.set_array([])
        plt.colorbar(sm_q, cax=cax_q, label="局所Q [W]")

        # ---- パス接続矢印 -----------------------------------------------
        self._draw_pass_arrows(ax, pass_cfg, tube, stagger_offset)

        # ---- 軸設定 -----------------------------------------------------
        ax.set_aspect("equal", adjustable="box")
        ax.set_xlim(-0.2, nc + 0.2)
        ax.set_ylim(-0.3, nr + 0.8 if stagger_offset > 0 else nr + 0.2)
        ax.set_xlabel("コラム (空気流れ方向 →)", fontsize=9)
        ax.set_ylabel("行 (row)", fontsize=9)
        ax.set_xticks(np.arange(nc) + 0.5)
        ax.set_xticklabels([f"col {i}" for i in range(nc)], fontsize=7)
        ax.set_yticks(np.arange(nr) + 0.5)
        ax.set_yticklabels([f"row {i}" for i in range(nr)], fontsize=7)

        arr = u"空気 →"
        ax.annotate(
            arr, xy=(0.98, 0.01), xycoords="axes fraction",
            fontsize=9, ha="right", va="bottom",
            color="navy",
            arrowprops=None,
        )

        arr_label = "千鳥配列" if tube.arrangement == "staggered" else "正方配列"
        ax.set_title(f"熱交換器グリッド ({arr_label})", fontsize=10)

    # ------------------------------------------------------------------
    def _draw_pass_arrows(
        self,
        ax,
        pass_cfg: PassConfiguration,
        tube: TubeGeometry,
        stagger_offset: float,
    ) -> None:
        """パスの水流れを矢印で表示"""
        for p in pass_cfg.passes:
            color = PASS_COLORS[p.pass_id % len(PASS_COLORS)]
            seq = p.tube_sequence
            for k in range(len(seq) - 1):
                r0, c0 = seq[k]
                r1, c1 = seq[k + 1]
                x0 = c0 + 0.5
                y0 = r0 + 0.5 + (stagger_offset if c0 % 2 == 1 else 0.0)
                x1 = c1 + 0.5
                y1 = r1 + 0.5 + (stagger_offset if c1 % 2 == 1 else 0.0)
                ax.annotate(
                    "",
                    xy=(x1, y1), xytext=(x0, y0),
                    arrowprops=dict(
                        arrowstyle="->",
                        color=color,
                        lw=1.2,
                        connectionstyle="arc3,rad=0.0",
                    ),
                    zorder=5,
                )
