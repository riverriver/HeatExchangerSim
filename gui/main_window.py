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
from gui.pass_editor import PassEditor
from gui.result_panel import ResultPanel


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("熱交換器シミュレーター")
        self.resize(1440, 860)

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
        self._pass_editor  = PassEditor()
        self._result_panel = ResultPanel()

        self._tabs.addTab(self._grid_view,    "グリッドビュー")
        self._tabs.addTab(self._pass_editor,  "パスエディター")
        self._tabs.addTab(self._result_panel, "計算結果")

        splitter.addWidget(self._tabs)
        splitter.setSizes([320, 1120])

        # ---- ステータスバー -----------------------------------------------
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage("準備完了")

        # ---- シグナル接続 -------------------------------------------------
        # ParamPanel → PassEditor: ジオメトリ変更時にグリッドを更新
        self._param_panel.geometry_changed.connect(self._on_geometry_changed)
        # ParamPanel → PassEditor: パスタイプ変更時にプリセットをエディターに反映
        self._param_panel.pass_preset_changed.connect(self._on_pass_preset_changed)
        # PassEditor → ParamPanel: 手動編集時にパラメータパネルへ通知
        self._pass_editor.pass_config_changed.connect(self._on_pass_editor_changed)
        # Run ボタン
        self._param_panel.run_requested.connect(self._on_run)

        # 初期ジオメトリをエディターに反映
        self._sync_editor_geometry()

    # ------------------------------------------------------------------
    def _sync_editor_geometry(self) -> None:
        """param_panel の現在のジオメトリをパスエディターに反映する。"""
        try:
            cfg = self._param_panel.build_config_for_editor()
        except ValueError:
            return
        self._pass_editor.set_geometry(cfg.tube)
        self._pass_editor.set_pass_config(cfg.pass_config, cfg.tube)

    def _on_geometry_changed(self) -> None:
        """管形状 (n_rows/n_cols/配列) が変わったときにパスエディターをリセット。"""
        try:
            cfg = self._param_panel.build_config_for_editor()
        except ValueError:
            return
        self._pass_editor.set_geometry(cfg.tube)

    def _on_pass_preset_changed(self) -> None:
        """プリセット変更をパスエディターに反映する。"""
        try:
            cfg = self._param_panel.build_config_for_editor()
        except ValueError:
            return
        self._pass_editor.set_geometry(cfg.tube)
        self._pass_editor.set_pass_config(cfg.pass_config, cfg.tube)

    def _on_pass_editor_changed(self, pass_cfg) -> None:
        """パスエディターで手動編集されたらパラメータパネルに通知。"""
        self._param_panel.set_custom_pass_config(pass_cfg)
        self._status.showMessage("パス設定を更新しました")

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

        self._grid_view.update_result(result, cfg.tube, cfg.pass_config)
        self._result_panel.update_result(
            result,
            cfg.water_inlet,
            cfg.air_cond,
            cfg.pass_config,
        )

        self._tabs.setCurrentIndex(2)   # 計算結果タブ

        msg = (
            f"Q = {result.Q_total/1000:.2f} kW  |  "
            f"ε = {result.effectiveness:.3f}  |  "
            f"空気平均出口温度 = {result.T_air_out_mean:.1f} °C"
        )
        self._status.showMessage(msg)
