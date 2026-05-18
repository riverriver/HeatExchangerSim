"""パラメータ入力パネル"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QFormLayout,
    QGroupBox, QDoubleSpinBox, QSpinBox,
    QComboBox, QPushButton, QMessageBox, QLabel,
)

from domain.geometry import TubeGeometry, FinGeometry
from domain.fluid import FluidProperties, WaterInlet, AirCondition, AIR, WATER
from domain.pass_config import (
    Pass, PassConfiguration,
    make_serpentine, make_parallel_passes, make_series_passes,
)
from domain.solver import SolverConfig, LateralMixingMode


@dataclass
class SimConfig:
    tube: TubeGeometry
    fin: FinGeometry
    air_prop: FluidProperties
    water_prop: FluidProperties
    air_cond: AirCondition
    water_inlet: WaterInlet
    pass_config: PassConfiguration
    solver_cfg: SolverConfig


def _dbl(val: float, lo: float, hi: float, dec: int = 3, step: float = 0.001) -> QDoubleSpinBox:
    sb = QDoubleSpinBox()
    sb.setRange(lo, hi)
    sb.setDecimals(dec)
    sb.setSingleStep(step)
    sb.setValue(val)
    return sb


def _int(val: int, lo: int, hi: int) -> QSpinBox:
    sb = QSpinBox()
    sb.setRange(lo, hi)
    sb.setValue(val)
    return sb


class ParamPanel(QWidget):
    run_requested     = pyqtSignal(object)  # SimConfig
    geometry_changed  = pyqtSignal()        # n_rows/n_cols/配列 変化時
    pass_preset_changed = pyqtSignal()      # パスタイプ変化時

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setSpacing(6)

        # カスタムパス (パスエディターから受け取る)
        self._custom_pass_cfg: PassConfiguration | None = None

        # ---- 管形状 -------------------------------------------------------
        grp_tube = QGroupBox("管形状 (Tube Geometry)")
        fl = QFormLayout(grp_tube)
        self.sb_do     = _dbl(0.010, 0.003, 0.05,  3, 0.001)
        self.sb_di     = _dbl(0.008, 0.002, 0.048, 3, 0.001)
        self.sb_length = _dbl(0.500, 0.05,  2.0,   3, 0.05)
        self.sb_Sl     = _dbl(0.025, 0.01,  0.1,   3, 0.001)
        self.sb_St     = _dbl(0.025, 0.01,  0.1,   3, 0.001)
        self.sb_nrows  = _int(4, 1, 20)
        self.sb_ncols  = _int(4, 1, 20)
        fl.addRow("管外径 do [m]",   self.sb_do)
        fl.addRow("管内径 di [m]",   self.sb_di)
        fl.addRow("管長さ L [m]",    self.sb_length)
        fl.addRow("縦ピッチ Sl [m]", self.sb_Sl)
        fl.addRow("横ピッチ St [m]", self.sb_St)
        fl.addRow("段数 n_rows",     self.sb_nrows)
        fl.addRow("列数 n_cols",     self.sb_ncols)
        root.addWidget(grp_tube)

        # ---- フィン形状 ---------------------------------------------------
        grp_fin = QGroupBox("フィン形状 (Fin Geometry)")
        fl2 = QFormLayout(grp_fin)
        self.sb_fp   = _dbl(0.002,  0.0005, 0.01,  4, 0.0005)
        self.sb_ft   = _dbl(0.0001, 0.00005, 0.001, 5, 0.00005)
        self.sb_kfin = _dbl(205.0,  10.0, 500.0,   1, 10.0)
        fl2.addRow("フィンピッチ [m]",  self.sb_fp)
        fl2.addRow("フィン厚さ [m]",    self.sb_ft)
        fl2.addRow("熱伝導率 [W/m·K]", self.sb_kfin)
        root.addWidget(grp_fin)

        # ---- 水側条件 -----------------------------------------------------
        grp_water = QGroupBox("水側条件 (Water Side)")
        fl3 = QFormLayout(grp_water)
        self.sb_Tw_in = _dbl(60.0,  0.0, 200.0, 1, 1.0)
        self.sb_Qw    = _dbl(0.100, 0.001, 10.0, 3, 0.01)
        fl3.addRow("入口温度 [°C]", self.sb_Tw_in)
        fl3.addRow("流量 [kg/s]",   self.sb_Qw)
        root.addWidget(grp_water)

        # ---- 空気側条件 ---------------------------------------------------
        grp_air = QGroupBox("空気側条件 (Air Side)")
        fl4 = QFormLayout(grp_air)
        self.sb_Ta_in = _dbl(25.0, -20.0, 60.0, 1, 1.0)
        self.sb_vel   = _dbl(2.0,   0.1,  20.0, 2, 0.1)
        fl4.addRow("入口温度 [°C]",  self.sb_Ta_in)
        fl4.addRow("前面風速 [m/s]", self.sb_vel)
        root.addWidget(grp_air)

        # ---- 配列・パス設定 -----------------------------------------------
        grp_cfg = QGroupBox("配列・パス設定")
        fl5 = QFormLayout(grp_cfg)

        self.cb_arrangement = QComboBox()
        self.cb_arrangement.addItems(["千鳥 (staggered)", "正方 (inline)"])
        fl5.addRow("管配列", self.cb_arrangement)

        self.cb_pass_type = QComboBox()
        self.cb_pass_type.addItems([
            "蛇行 (serpentine)", "並列 (parallel)",
            "直列2パス (series)", "カスタム (エディターから)",
        ])
        fl5.addRow("パスタイプ", self.cb_pass_type)

        self.sb_n_parallel = _int(2, 2, 8)
        self.sb_n_parallel.setEnabled(False)
        fl5.addRow("並列パス数", self.sb_n_parallel)

        self.cb_mixing = QComboBox()
        self.cb_mixing.addItems(["STREAM (推奨)", "SIMPLE", "NONE"])
        fl5.addRow("横混合モード", self.cb_mixing)

        root.addWidget(grp_cfg)

        # ---- Run ボタン --------------------------------------------------
        self.btn_run = QPushButton("▶ Run")
        self.btn_run.setMinimumHeight(36)
        self.btn_run.setStyleSheet("font-weight: bold; font-size: 14px;")
        root.addWidget(self.btn_run)
        root.addStretch()

        # シグナル接続
        self.cb_pass_type.currentIndexChanged.connect(self._on_pass_type_changed)
        self.cb_arrangement.currentIndexChanged.connect(self._on_arrangement_changed)
        self.sb_nrows.valueChanged.connect(self._on_geometry_changed)
        self.sb_ncols.valueChanged.connect(self._on_geometry_changed)
        self.cb_arrangement.currentIndexChanged.connect(self._on_geometry_changed)
        self.btn_run.clicked.connect(self._on_run_clicked)

    # ------------------------------------------------------------------
    # 外部インターフェース (パスエディターとの同期)
    # ------------------------------------------------------------------
    def set_custom_pass_config(self, cfg: PassConfiguration) -> None:
        """パスエディターで手動定義されたパス設定を受け取る。"""
        self._custom_pass_cfg = cfg
        # "カスタム" に切り替え (シグナルを抑制して循環を防ぐ)
        self.cb_pass_type.blockSignals(True)
        self.cb_pass_type.setCurrentIndex(3)
        self.cb_pass_type.blockSignals(False)

    def build_config_for_editor(self) -> SimConfig:
        """パスエディター初期化用: パス設定も含む SimConfig を返す (例外あり)。"""
        return self._build_config(skip_pass_validation=True)

    # ------------------------------------------------------------------
    # スロット
    # ------------------------------------------------------------------
    def _on_pass_type_changed(self, idx: int) -> None:
        self.sb_n_parallel.setEnabled(idx == 1)
        if idx != 3:
            self._custom_pass_cfg = None
        self.pass_preset_changed.emit()

    def _on_arrangement_changed(self, idx: int) -> None:
        is_inline = idx == 1
        self.cb_mixing.setEnabled(not is_inline)
        if is_inline:
            self.cb_mixing.setCurrentIndex(2)

    def _on_geometry_changed(self) -> None:
        self._custom_pass_cfg = None
        if self.cb_pass_type.currentIndex() == 3:
            self.cb_pass_type.blockSignals(True)
            self.cb_pass_type.setCurrentIndex(0)
            self.cb_pass_type.blockSignals(False)
        self.geometry_changed.emit()

    def _on_run_clicked(self) -> None:
        try:
            cfg = self._build_config()
        except ValueError as e:
            QMessageBox.warning(self, "入力エラー", str(e))
            return
        self.run_requested.emit(cfg)

    # ------------------------------------------------------------------
    # 設定ビルド
    # ------------------------------------------------------------------
    def _build_config(self, skip_pass_validation: bool = False) -> SimConfig:
        do = self.sb_do.value()
        di = self.sb_di.value()
        if di >= do:
            raise ValueError(
                f"管内径 di ({di*1000:.1f} mm) は外径 do ({do*1000:.1f} mm) より小さくする必要があります"
            )

        fp = self.sb_fp.value()
        ft = self.sb_ft.value()
        if ft >= fp:
            raise ValueError("フィン厚さはフィンピッチより小さくする必要があります")

        Sl = self.sb_Sl.value()
        St = self.sb_St.value()
        if Sl <= do or St <= do:
            raise ValueError("ピッチは管外径より大きくする必要があります")

        nr = self.sb_nrows.value()
        nc = self.sb_ncols.value()
        arrangement: str = "staggered" if self.cb_arrangement.currentIndex() == 0 else "inline"

        tube = TubeGeometry(
            do=do, di=di, length=self.sb_length.value(),
            Sl=Sl, St=St, n_rows=nr, n_cols=nc,
            arrangement=arrangement,
        )
        fin = FinGeometry(pitch=fp, thickness=ft, k_fin=self.sb_kfin.value())

        pass_cfg = self._build_pass_config(nr, nc, skip_pass_validation)

        mixing_map = {
            0: LateralMixingMode.STREAM,
            1: LateralMixingMode.SIMPLE,
            2: LateralMixingMode.NONE,
        }
        solver_cfg = SolverConfig(mixing_mode=mixing_map[self.cb_mixing.currentIndex()])

        return SimConfig(
            tube=tube, fin=fin,
            air_prop=AIR, water_prop=WATER,
            air_cond=AirCondition(T_in=self.sb_Ta_in.value(), velocity=self.sb_vel.value()),
            water_inlet=WaterInlet(T_in=self.sb_Tw_in.value(), flow_rate=self.sb_Qw.value()),
            pass_config=pass_cfg,
            solver_cfg=solver_cfg,
        )

    def _build_pass_config(
        self, nr: int, nc: int, skip_validation: bool
    ) -> PassConfiguration:
        idx = self.cb_pass_type.currentIndex()

        if idx == 3:  # カスタム
            if self._custom_pass_cfg is not None:
                return self._custom_pass_cfg
            # カスタムが未設定ならフォールバック
            return make_serpentine(nr, nc)

        if idx == 0:
            return make_serpentine(nr, nc)

        if idx == 1:
            n_par = self.sb_n_parallel.value()
            if not skip_validation and nc % n_par != 0:
                raise ValueError(f"列数 ({nc}) は並列パス数 ({n_par}) の倍数にしてください")
            try:
                return make_parallel_passes(nr, nc, n_par)
            except ValueError:
                return make_serpentine(nr, nc)

        # idx == 2: 直列
        if not skip_validation and nc % 2 != 0:
            raise ValueError(f"直列2パスには列数 ({nc}) を偶数にしてください")
        try:
            return make_series_passes(nr, nc)
        except ValueError:
            return make_serpentine(nr, nc)

    # ------------------------------------------------------------------
    # JSON シリアライズ / デシリアライズ
    # ------------------------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        """全パラメータを JSON 互換の dict に変換する。"""
        custom_pass = None
        if self._custom_pass_cfg is not None:
            custom_pass = {
                "passes": [
                    {
                        "pass_id": p.pass_id,
                        "tube_sequence": [list(t) for t in p.tube_sequence],
                        "inlet_source": p.inlet_source,
                    }
                    for p in self._custom_pass_cfg.passes
                ]
            }
        return {
            "version": 1,
            "tube": {
                "do": self.sb_do.value(),
                "di": self.sb_di.value(),
                "length": self.sb_length.value(),
                "Sl": self.sb_Sl.value(),
                "St": self.sb_St.value(),
                "n_rows": self.sb_nrows.value(),
                "n_cols": self.sb_ncols.value(),
                "arrangement": "staggered" if self.cb_arrangement.currentIndex() == 0 else "inline",
            },
            "fin": {
                "pitch": self.sb_fp.value(),
                "thickness": self.sb_ft.value(),
                "k_fin": self.sb_kfin.value(),
            },
            "water": {
                "T_in": self.sb_Tw_in.value(),
                "flow_rate": self.sb_Qw.value(),
            },
            "air": {
                "T_in": self.sb_Ta_in.value(),
                "velocity": self.sb_vel.value(),
            },
            "pass_type_idx": self.cb_pass_type.currentIndex(),
            "n_parallel": self.sb_n_parallel.value(),
            "mixing_idx": self.cb_mixing.currentIndex(),
            "custom_pass": custom_pass,
        }

    def from_dict(self, d: dict[str, Any]) -> None:
        """dict から全ウィジェットの値を復元する。"""
        # ウィジェット変更シグナルを一時抑制して連鎖を防ぐ
        def _set_dbl(sb: QDoubleSpinBox, v: float) -> None:
            sb.blockSignals(True); sb.setValue(v); sb.blockSignals(False)

        def _set_int(sb: QSpinBox, v: int) -> None:
            sb.blockSignals(True); sb.setValue(v); sb.blockSignals(False)

        def _set_cb(cb: QComboBox, v: int) -> None:
            cb.blockSignals(True); cb.setCurrentIndex(v); cb.blockSignals(False)

        tube = d.get("tube", {})
        _set_dbl(self.sb_do,     tube.get("do",     0.010))
        _set_dbl(self.sb_di,     tube.get("di",     0.008))
        _set_dbl(self.sb_length, tube.get("length", 0.500))
        _set_dbl(self.sb_Sl,     tube.get("Sl",     0.025))
        _set_dbl(self.sb_St,     tube.get("St",     0.025))
        _set_int(self.sb_nrows,  tube.get("n_rows", 4))
        _set_int(self.sb_ncols,  tube.get("n_cols", 4))
        arr = tube.get("arrangement", "staggered")
        _set_cb(self.cb_arrangement, 0 if arr == "staggered" else 1)

        fin = d.get("fin", {})
        _set_dbl(self.sb_fp,   fin.get("pitch",     0.002))
        _set_dbl(self.sb_ft,   fin.get("thickness", 0.0001))
        _set_dbl(self.sb_kfin, fin.get("k_fin",     205.0))

        water = d.get("water", {})
        _set_dbl(self.sb_Tw_in, water.get("T_in",      60.0))
        _set_dbl(self.sb_Qw,    water.get("flow_rate", 0.1))

        air = d.get("air", {})
        _set_dbl(self.sb_Ta_in, air.get("T_in",     25.0))
        _set_dbl(self.sb_vel,   air.get("velocity", 2.0))

        _set_int(self.sb_n_parallel, d.get("n_parallel", 2))
        _set_cb(self.cb_mixing,      d.get("mixing_idx", 0))

        custom = d.get("custom_pass")
        if custom:
            passes = [
                Pass(
                    pass_id=p["pass_id"],
                    tube_sequence=[tuple(t) for t in p["tube_sequence"]],  # type: ignore[arg-type]
                    inlet_source=p.get("inlet_source"),
                )
                for p in custom["passes"]
            ]
            try:
                self._custom_pass_cfg = PassConfiguration(passes=passes)
                _set_cb(self.cb_pass_type, 3)
            except ValueError:
                self._custom_pass_cfg = None
                _set_cb(self.cb_pass_type, d.get("pass_type_idx", 0))
        else:
            self._custom_pass_cfg = None
            _set_cb(self.cb_pass_type, d.get("pass_type_idx", 0))

        # inline の場合は mixing を NONE に
        if self.cb_arrangement.currentIndex() == 1:
            _set_cb(self.cb_mixing, 2)
            self.cb_mixing.setEnabled(False)
        else:
            self.cb_mixing.setEnabled(True)
        self.sb_n_parallel.setEnabled(self.cb_pass_type.currentIndex() == 1)
