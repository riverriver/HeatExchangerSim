"""メインウィンドウ"""

from __future__ import annotations

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout,
    QSplitter, QScrollArea, QTabWidget,
    QMessageBox, QStatusBar,
)
from PyQt6.QtCore import Qt

from domain.solver import run as solver_run
from gui.param_panel import ParamPanel, SimConfig
from gui.grid_view import GridView
from gui.result_panel import ResultPanel


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("熱交換器シミュレーター")
        self.resize(1400, 820)

        # ---- 中央ウィジェット ---------------------------------------------
        central = QWidget()
        self.setCentralWidget(central)
        h_layout = QHBoxLayout(central)
        h_layout.setContentsMargins(4, 4, 4, 4)
        h_layout.setSpacing(0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        h_layout.addWidget(splitter)

        # ---- 左: パラメータパネル (スクロール可) --------------------------
        self._param_panel = ParamPanel()
        scroll = QScrollArea()
        scroll.setWidget(self._param_panel)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(300)
        scroll.setMaximumWidth(360)
        splitter.addWidget(scroll)

        # ---- 右: タブビュー -----------------------------------------------
        self._tabs = QTabWidget()

        self._grid_view    = GridView()
        self._result_panel = ResultPanel()

        self._tabs.addTab(self._grid_view,    "グリッドビュー")
        self._tabs.addTab(self._result_panel, "計算結果")

        splitter.addWidget(self._tabs)
        splitter.setSizes([320, 1080])

        # ---- ステータスバー -----------------------------------------------
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage("準備完了")

        # ---- シグナル接続 -------------------------------------------------
        self._param_panel.run_requested.connect(self._on_run)

    # ------------------------------------------------------------------
    def _on_run(self, cfg: SimConfig) -> None:
        self._status.showMessage("計算中...")
        self.repaint()

        try:
            result = solver_run(
                tube        = cfg.tube,
                fin         = cfg.fin,
                air_prop    = cfg.air_prop,
                water_prop  = cfg.water_prop,
                air_cond    = cfg.air_cond,
                water_inlet = cfg.water_inlet,
                pass_config = cfg.pass_config,
                solver_cfg  = cfg.solver_cfg,
            )
        except Exception as exc:
            QMessageBox.critical(self, "計算エラー", str(exc))
            self._status.showMessage("エラー")
            return

        # ビューを更新
        self._grid_view.update_result(result, cfg.tube, cfg.pass_config)
        self._result_panel.update_result(
            result,
            cfg.water_inlet,
            cfg.air_cond,
            cfg.pass_config,
        )

        # 結果タブに切り替え
        self._tabs.setCurrentIndex(1)

        msg = (
            f"Q = {result.Q_total/1000:.2f} kW  |  "
            f"ε = {result.effectiveness:.3f}  |  "
            f"空気平均出口温度 = {result.T_air_out_mean:.1f} °C"
        )
        self._status.showMessage(msg)
