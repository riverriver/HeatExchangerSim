"""
パラメトリックスイープパネル

1つのパラメータを範囲指定してソルバーを連続実行し、
Q / ε / 空気出口温度 / 水出口温度 の4指標を同時プロット。

サポートするスイープパラメータ:
  - 前面風速 [m/s]
  - 水流量 [kg/s]
  - 水入口温度 [°C]
  - 空気入口温度 [°C]
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QLabel, QDoubleSpinBox, QSpinBox,
    QComboBox, QPushButton, QMessageBox, QProgressBar,
    QTableWidget, QTableWidgetItem, QSizePolicy,
)

from domain.fluid import WaterInlet, AirCondition
from domain.geometry import TubeGeometry
from domain.solver import run as solver_run
from gui.param_panel import SimConfig


# ---------------------------------------------------------------------------
# スイープパラメータ定義
# ---------------------------------------------------------------------------

SWEEP_PARAMS = [
    ("前面風速 [m/s]",       "velocity",    0.1,  20.0,  2.0),
    ("水流量 [kg/s]",        "flow_rate",   0.01,  5.0,  0.1),
    ("水入口温度 [°C]",      "water_T_in",  10.0, 150.0, 60.0),
    ("空気入口温度 [°C]",    "air_T_in",   -20.0,  60.0, 25.0),
]

OUTPUT_LABELS = [
    "Q_total [kW]",
    "効率 ε",
    "空気出口平均温度 [°C]",
    "水出口温度 (平均) [°C]",
]


def _make_varied_config(base: SimConfig, param_key: str, value: float) -> SimConfig:
    """base をコピーして指定パラメータだけ value に置換した SimConfig を返す。"""
    tube = base.tube
    air  = base.air_cond
    wat  = base.water_inlet

    if param_key == "velocity":
        air = AirCondition(T_in=air.T_in, velocity=value)
    elif param_key == "flow_rate":
        wat = WaterInlet(T_in=wat.T_in, flow_rate=value)
    elif param_key == "water_T_in":
        wat = WaterInlet(T_in=value, flow_rate=wat.flow_rate)
    elif param_key == "air_T_in":
        air = AirCondition(T_in=value, velocity=air.velocity)

    return SimConfig(
        tube=tube, fin=base.fin,
        air_prop=base.air_prop, water_prop=base.water_prop,
        air_cond=air, water_inlet=wat,
        pass_config=base.pass_config,
        solver_cfg=base.solver_cfg,
    )


def _extract_outputs(result) -> list[float]:
    """SolverResult から4指標を取り出す。"""
    T_w_mean = float(np.mean(list(result.T_water_out_per_pass.values())))
    return [
        result.Q_total / 1000,
        result.effectiveness,
        result.T_air_out_mean,
        T_w_mean,
    ]


# ---------------------------------------------------------------------------
# SweepPanel
# ---------------------------------------------------------------------------

class SweepPanel(QWidget):
    def __init__(
        self,
        get_config: Callable[[], SimConfig | None],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._get_config = get_config
        self._results: list[tuple[float, list[float]]] = []  # (param_val, outputs)
        self._build_ui()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(6)

        # ---- コントロール行 -----------------------------------------------
        ctrl = QGroupBox("スイープ設定")
        fl = QFormLayout(ctrl)

        self._cb_param = QComboBox()
        for label, *_ in SWEEP_PARAMS:
            self._cb_param.addItem(label)
        self._cb_param.currentIndexChanged.connect(self._on_param_changed)
        fl.addRow("スイープパラメータ:", self._cb_param)

        range_row = QHBoxLayout()
        self._sb_min   = _dbl(0.5,  -999, 9999, 3)
        self._sb_max   = _dbl(5.0,  -999, 9999, 3)
        self._sb_steps = _int(20, 2, 200)
        range_row.addWidget(QLabel("最小:"))
        range_row.addWidget(self._sb_min)
        range_row.addWidget(QLabel("最大:"))
        range_row.addWidget(self._sb_max)
        range_row.addWidget(QLabel("ステップ数:"))
        range_row.addWidget(self._sb_steps)
        fl.addRow("範囲:", range_row)

        btn_row = QHBoxLayout()
        self._btn_run = QPushButton("▶ スイープ実行")
        self._btn_run.setMinimumHeight(32)
        self._btn_run.setStyleSheet("font-weight: bold;")
        self._btn_run.clicked.connect(self._on_run)
        self._btn_clear = QPushButton("クリア")
        self._btn_clear.clicked.connect(self._on_clear)
        btn_row.addWidget(self._btn_run)
        btn_row.addWidget(self._btn_clear)
        btn_row.addStretch()
        fl.addRow("", btn_row)

        self._progress = QProgressBar()
        self._progress.setVisible(False)
        fl.addRow("進捗:", self._progress)

        root.addWidget(ctrl)

        # ---- チャート (2×2) -----------------------------------------------
        self._fig, self._axes = plt.subplots(
            2, 2, figsize=(10, 6),
            gridspec_kw={"hspace": 0.45, "wspace": 0.35},
        )
        self._canvas  = FigureCanvasQTAgg(self._fig)
        self._toolbar = NavigationToolbar2QT(self._canvas, self)
        root.addWidget(self._toolbar)
        root.addWidget(self._canvas)

        # ---- 数値テーブル ------------------------------------------------
        self._table = QTableWidget()
        self._table.setMaximumHeight(160)
        root.addWidget(self._table)

        # 初期パラメータ範囲を反映
        self._on_param_changed(0)

    # ------------------------------------------------------------------
    def _on_param_changed(self, idx: int) -> None:
        _, _, lo, hi, default = SWEEP_PARAMS[idx]
        margin = (hi - lo) * 0.1
        self._sb_min.setValue(max(lo, default - margin * 3))
        self._sb_max.setValue(min(hi, default + margin * 3))

    def _on_clear(self) -> None:
        self._results.clear()
        self._redraw()
        self._table.setRowCount(0)

    # ------------------------------------------------------------------
    def _on_run(self) -> None:
        base_cfg = self._get_config()
        if base_cfg is None:
            QMessageBox.warning(self, "設定エラー", "パラメータパネルで設定を確認してください")
            return

        param_idx  = self._cb_param.currentIndex()
        param_key  = SWEEP_PARAMS[param_idx][1]
        param_label = SWEEP_PARAMS[param_idx][0]
        v_min  = self._sb_min.value()
        v_max  = self._sb_max.value()
        n_step = self._sb_steps.value()

        if v_min >= v_max:
            QMessageBox.warning(self, "範囲エラー", "最小値 < 最大値 にしてください")
            return

        values = np.linspace(v_min, v_max, n_step)

        self._progress.setVisible(True)
        self._progress.setMaximum(n_step)
        self._btn_run.setEnabled(False)

        sweep_results: list[tuple[float, list[float]]] = []
        for i, v in enumerate(values):
            self._progress.setValue(i + 1)
            self.repaint()
            try:
                cfg = _make_varied_config(base_cfg, param_key, v)
                result = solver_run(
                    tube=cfg.tube, fin=cfg.fin,
                    air_prop=cfg.air_prop, water_prop=cfg.water_prop,
                    air_cond=cfg.air_cond, water_inlet=cfg.water_inlet,
                    pass_config=cfg.pass_config, solver_cfg=cfg.solver_cfg,
                )
                sweep_results.append((float(v), _extract_outputs(result)))
            except Exception as e:
                sweep_results.append((float(v), [float("nan")] * 4))

        self._progress.setVisible(False)
        self._btn_run.setEnabled(True)

        self._results = sweep_results
        self._current_param_label = param_label
        self._redraw()
        self._update_table(param_label)

    # ------------------------------------------------------------------
    def _redraw(self) -> None:
        for ax in self._axes.flat:
            ax.clear()

        if not self._results:
            for ax in self._axes.flat:
                ax.text(0.5, 0.5, "スイープ実行ボタンを押してください",
                        transform=ax.transAxes,
                        ha="center", va="center", color="gray", fontsize=10)
            self._canvas.draw()
            return

        xs = [r[0] for r in self._results]
        ys_list = [r[1] for r in self._results]  # [[q, eps, T_air, T_w], ...]
        param_label = getattr(self, "_current_param_label", "パラメータ")

        colors = ["#E53935", "#1E88E5", "#43A047", "#FB8C00"]
        for i, (ax, label, color) in enumerate(
            zip(self._axes.flat, OUTPUT_LABELS, colors)
        ):
            ys = [row[i] for row in ys_list]
            ax.plot(xs, ys, color=color, lw=2, marker="o", markersize=3)
            ax.set_xlabel(param_label, fontsize=8)
            ax.set_ylabel(label, fontsize=8)
            ax.set_title(label, fontsize=9)
            ax.tick_params(labelsize=7)
            ax.grid(True, alpha=0.3)

            # 現在設定値の縦線
            base_cfg = self._get_config()
            if base_cfg is not None:
                param_key = SWEEP_PARAMS[self._cb_param.currentIndex()][1]
                cur_val = {
                    "velocity":    base_cfg.air_cond.velocity,
                    "flow_rate":   base_cfg.water_inlet.flow_rate,
                    "water_T_in":  base_cfg.water_inlet.T_in,
                    "air_T_in":    base_cfg.air_cond.T_in,
                }.get(param_key)
                if cur_val is not None:
                    ax.axvline(cur_val, color="gray", ls="--", lw=1, alpha=0.7)

        self._canvas.draw()

    # ------------------------------------------------------------------
    def _update_table(self, param_label: str) -> None:
        headers = [param_label] + OUTPUT_LABELS
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        self._table.setRowCount(len(self._results))

        for row, (v, outputs) in enumerate(self._results):
            self._table.setItem(row, 0, QTableWidgetItem(f"{v:.4g}"))
            for col, val in enumerate(outputs):
                self._table.setItem(row, col + 1, QTableWidgetItem(f"{val:.4g}"))

        self._table.resizeColumnsToContents()


# ---------------------------------------------------------------------------
# ヘルパー
# ---------------------------------------------------------------------------

def _dbl(val: float, lo: float, hi: float, dec: int = 2) -> QDoubleSpinBox:
    sb = QDoubleSpinBox()
    sb.setRange(lo, hi)
    sb.setDecimals(dec)
    sb.setValue(val)
    return sb


def _int(val: int, lo: int, hi: int) -> QSpinBox:
    sb = QSpinBox()
    sb.setRange(lo, hi)
    sb.setValue(val)
    return sb
