"""
パスエディター (Phase 3)

機能:
  - 管グリッドをクリックして水の流れ順序 (パス) を定義
  - 複数パスを色分けで管理
  - 直列接続ダイアログで Pass間の接続を設定
  - プリセット (蛇行/並列) をワンクリックで適用
  - PassConfiguration オブジェクトとして出力

操作:
  - 左クリック: 現在パスに管を追加 (既登録管は不可)
  - 右クリック: 現在パスから管を削除
  - Shift+クリック: 別パスに登録済み管でも強制移動
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import matplotlib
matplotlib.use("QtAgg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QPushButton, QTextEdit,
    QDialog, QDialogButtonBox, QFormLayout,
    QMessageBox, QSizePolicy,
)

from domain.geometry import TubeGeometry
from domain.pass_config import Pass, PassConfiguration, make_serpentine, make_parallel_passes


PASS_COLORS = [
    "#2196F3",  # blue
    "#F44336",  # red
    "#4CAF50",  # green
    "#FF9800",  # orange
    "#9C27B0",  # purple
    "#00BCD4",  # cyan
    "#795548",  # brown
    "#607D8B",  # blue-grey
]
UNASSIGNED_COLOR = "#BDBDBD"
TUBE_RADIUS = 0.38   # data coordinates


# ---------------------------------------------------------------------------
# 直列接続設定ダイアログ
# ---------------------------------------------------------------------------

class _SeriesDialog(QDialog):
    def __init__(self, n_passes: int, current_sources: list[int | None], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("直列接続設定")
        self.setMinimumWidth(320)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("各パスの水入口を設定してください:"))

        self._combos: list[tuple[int, QComboBox]] = []
        form = QFormLayout()
        for pid in range(n_passes):
            cb = QComboBox()
            cb.addItem("外部入口 (独立パス)")
            for src in range(n_passes):
                if src != pid:
                    cb.addItem(f"Pass {src} の出口から")
            src = current_sources[pid]
            if src is None:
                cb.setCurrentIndex(0)
            else:
                # src が pid より小さければ index = src+1, 大きければ src
                items = ["外部入口"] + [f"Pass {s} の出口から" for s in range(n_passes) if s != pid]
                for i, item in enumerate(items):
                    if src is not None and f"Pass {src}" in item:
                        cb.setCurrentIndex(i)
                        break
            self._combos.append((pid, cb))
            form.addRow(f"Pass {pid}:", cb)
        layout.addLayout(form)

        btn_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btn_box.accepted.connect(self.accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def get_sources(self) -> list[int | None]:
        result: list[int | None] = []
        for pid, cb in self._combos:
            idx = cb.currentIndex()
            if idx == 0:
                result.append(None)
            else:
                # reconstruct source pass_id from combo item
                text = cb.currentText()
                # "Pass X の出口から" → X
                src_id = int(text.split("Pass ")[1].split(" ")[0])
                result.append(src_id)
        return result


# ---------------------------------------------------------------------------
# パスエディター本体
# ---------------------------------------------------------------------------

class PassEditor(QWidget):
    """インタラクティブなパス接続エディター。"""

    pass_config_changed = pyqtSignal(object)  # PassConfiguration

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tube: TubeGeometry | None = None

        # 内部状態: パスID → 管インデックスのリスト (順序 = 水の流れ順)
        self._sequences: list[list[tuple[int, int]]] = [[]]
        self._inlet_sources: list[int | None] = [None]   # パスID → inlet_source
        self._current_pass: int = 0

        self._build_ui()

    # ------------------------------------------------------------------
    # UI 構築
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setSpacing(4)

        # ---- ツールバー --------------------------------------------------
        tb = QHBoxLayout()
        tb.setSpacing(6)

        tb.addWidget(QLabel("編集中:"))
        self._cb_pass = QComboBox()
        self._cb_pass.addItem("Pass 0")
        self._cb_pass.setMinimumWidth(80)
        self._cb_pass.currentIndexChanged.connect(self._on_pass_selected)
        tb.addWidget(self._cb_pass)

        btn_new = QPushButton("＋ 新規パス")
        btn_new.clicked.connect(self._on_new_pass)
        tb.addWidget(btn_new)

        btn_del = QPushButton("✕ パス削除")
        btn_del.clicked.connect(self._on_delete_pass)
        tb.addWidget(btn_del)

        btn_series = QPushButton("⇒ 直列接続")
        btn_series.clicked.connect(self._on_series_dialog)
        tb.addWidget(btn_series)

        tb.addSpacing(12)
        tb.addWidget(QLabel("プリセット:"))
        self._cb_preset = QComboBox()
        self._cb_preset.addItems(["蛇行 (serpentine)", "並列 2パス", "並列 4パス"])
        tb.addWidget(self._cb_preset)

        btn_preset = QPushButton("適用")
        btn_preset.clicked.connect(self._on_apply_preset)
        tb.addWidget(btn_preset)

        tb.addStretch()

        btn_clear = QPushButton("クリア")
        btn_clear.clicked.connect(self._on_clear)
        tb.addWidget(btn_clear)

        root.addLayout(tb)

        # ---- Matplotlib キャンバス ----------------------------------------
        self._fig, self._ax = plt.subplots(figsize=(8, 5))
        self._canvas = FigureCanvasQTAgg(self._fig)
        self._canvas.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        nav = NavigationToolbar2QT(self._canvas, self)
        root.addWidget(nav)
        root.addWidget(self._canvas)

        self._cid = self._canvas.mpl_connect("button_press_event", self._on_canvas_click)

        # ---- サマリー表示 ------------------------------------------------
        self._summary = QTextEdit()
        self._summary.setReadOnly(True)
        self._summary.setMaximumHeight(80)
        self._summary.setStyleSheet("font-family: monospace; font-size: 11px;")
        root.addWidget(self._summary)

        self._draw()

    # ------------------------------------------------------------------
    # 外部インターフェース
    # ------------------------------------------------------------------
    def set_geometry(self, tube: TubeGeometry) -> None:
        """管形状が変わったときに呼び出す。状態をリセットして再描画。"""
        self._tube = tube
        self._sequences = [[]]
        self._inlet_sources = [None]
        self._current_pass = 0
        self._refresh_pass_combo()
        self._draw()

    def set_pass_config(self, cfg: PassConfiguration, tube: TubeGeometry) -> None:
        """既存の PassConfiguration をエディターに読み込む。"""
        self._tube = tube
        n = len(cfg.passes)
        self._sequences = [list(p.tube_sequence) for p in cfg.passes]
        self._inlet_sources = [p.inlet_source for p in cfg.passes]
        self._current_pass = 0
        self._refresh_pass_combo()
        self._draw()

    def get_pass_config(self) -> PassConfiguration | None:
        """現在の状態から PassConfiguration を生成して返す。空パスは除外。"""
        if self._tube is None:
            return None
        passes = []
        for pid, (seq, src) in enumerate(zip(self._sequences, self._inlet_sources)):
            if seq:
                passes.append(Pass(pass_id=pid, tube_sequence=list(seq), inlet_source=src))
        if not passes:
            return None
        # pass_id を 0 から連番に振り直す
        id_map = {p.pass_id: i for i, p in enumerate(passes)}
        renumbered = []
        for i, p in enumerate(passes):
            new_src = id_map.get(p.inlet_source) if p.inlet_source is not None else None
            renumbered.append(Pass(pass_id=i, tube_sequence=p.tube_sequence, inlet_source=new_src))
        try:
            return PassConfiguration(passes=renumbered)
        except ValueError as e:
            QMessageBox.warning(self, "無効なパス設定", str(e))
            return None

    # ------------------------------------------------------------------
    # ツールバーイベント
    # ------------------------------------------------------------------
    def _on_pass_selected(self, idx: int) -> None:
        self._current_pass = idx
        self._draw()

    def _on_new_pass(self) -> None:
        self._sequences.append([])
        self._inlet_sources.append(None)
        self._refresh_pass_combo()
        self._cb_pass.setCurrentIndex(len(self._sequences) - 1)
        self._draw()

    def _on_delete_pass(self) -> None:
        if len(self._sequences) <= 1:
            QMessageBox.information(self, "削除不可", "最低1パスは必要です")
            return
        pid = self._current_pass
        self._sequences.pop(pid)
        self._inlet_sources.pop(pid)
        # inlet_source の参照を修正
        for i in range(len(self._inlet_sources)):
            src = self._inlet_sources[i]
            if src == pid:
                self._inlet_sources[i] = None
            elif src is not None and src > pid:
                self._inlet_sources[i] = src - 1
        self._current_pass = max(0, pid - 1)
        self._refresh_pass_combo()
        self._cb_pass.setCurrentIndex(self._current_pass)
        self._draw()
        self._emit()

    def _on_series_dialog(self) -> None:
        n = len(self._sequences)
        dlg = _SeriesDialog(n, list(self._inlet_sources), self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_sources = dlg.get_sources()
            self._inlet_sources = new_sources
            self._draw()
            self._emit()

    def _on_apply_preset(self) -> None:
        if self._tube is None:
            return
        nr = self._tube.n_rows
        nc = self._tube.n_cols
        idx = self._cb_preset.currentIndex()
        try:
            if idx == 0:
                cfg = make_serpentine(nr, nc)
            elif idx == 1:
                if nc % 2 != 0:
                    raise ValueError("並列2パスには列数を偶数にしてください")
                cfg = make_parallel_passes(nr, nc, 2)
            else:
                if nc % 4 != 0:
                    raise ValueError("並列4パスには列数を4の倍数にしてください")
                cfg = make_parallel_passes(nr, nc, 4)
        except ValueError as e:
            QMessageBox.warning(self, "プリセットエラー", str(e))
            return
        self.set_pass_config(cfg, self._tube)
        self._emit()

    def _on_clear(self) -> None:
        self._sequences = [[]]
        self._inlet_sources = [None]
        self._current_pass = 0
        self._refresh_pass_combo()
        self._draw()
        self._emit()

    # ------------------------------------------------------------------
    # クリックイベント
    # ------------------------------------------------------------------
    def _on_canvas_click(self, event) -> None:
        if self._tube is None or event.inaxes != self._ax:
            return
        x, y = event.xdata, event.ydata
        nearest, dist = self._find_nearest_tube(x, y)
        if dist > TUBE_RADIUS + 0.05:
            return

        row, col = nearest
        shift_held = (event.key == "shift")

        if event.button == 1:  # 左クリック: 追加
            # 既に他のパスにある場合はシフトを要求
            owner = self._owner_of(row, col)
            if owner is not None and owner != self._current_pass:
                if not shift_held:
                    self._summary.setText(
                        f"この管は Pass {owner} に登録済みです。"
                        "Shift+クリックで強制移動できます。"
                    )
                    return
                # 強制移動: 他パスから削除
                self._sequences[owner] = [
                    t for t in self._sequences[owner] if t != (row, col)
                ]
            if owner == self._current_pass:
                # 同一パス内: 削除 (トグル)
                self._sequences[self._current_pass] = [
                    t for t in self._sequences[self._current_pass] if t != (row, col)
                ]
            else:
                self._sequences[self._current_pass].append((row, col))

        elif event.button == 3:  # 右クリック: 現在パスから削除
            self._sequences[self._current_pass] = [
                t for t in self._sequences[self._current_pass] if t != (row, col)
            ]

        self._draw()
        self._emit()

    def _owner_of(self, row: int, col: int) -> int | None:
        for pid, seq in enumerate(self._sequences):
            if (row, col) in seq:
                return pid
        return None

    def _find_nearest_tube(
        self, x: float, y: float
    ) -> tuple[tuple[int, int], float]:
        assert self._tube is not None
        best_idx = (0, 0)
        best_dist = float("inf")
        stagger = 0.5 if self._tube.arrangement == "staggered" else 0.0
        for row in range(self._tube.n_rows):
            for col in range(self._tube.n_cols):
                cx = col + 0.5
                cy = row + 0.5 + (stagger if col % 2 == 1 else 0.0)
                d = math.hypot(x - cx, y - cy)
                if d < best_dist:
                    best_dist = d
                    best_idx = (row, col)
        return best_idx, best_dist

    # ------------------------------------------------------------------
    # 描画
    # ------------------------------------------------------------------
    def _draw(self) -> None:
        self._ax.clear()
        if self._tube is None:
            self._ax.text(
                0.5, 0.5, "パラメータを設定してください",
                transform=self._ax.transAxes,
                ha="center", va="center", color="gray", fontsize=12,
            )
            self._canvas.draw()
            return

        nr = self._tube.n_rows
        nc = self._tube.n_cols
        stagger = 0.5 if self._tube.arrangement == "staggered" else 0.0

        # ---- グリッド背景 ------------------------------------------------
        for col in range(nc):
            for row in range(nr):
                cx = col + 0.5
                cy = row + 0.5 + (stagger if col % 2 == 1 else 0.0)
                owner = self._owner_of(row, col)
                is_current = (owner == self._current_pass)

                # 管の色
                if owner is None:
                    face = UNASSIGNED_COLOR
                    edge = "#9E9E9E"
                else:
                    face = PASS_COLORS[owner % len(PASS_COLORS)]
                    edge = "black" if is_current else "#555555"

                lw = 2.0 if is_current and owner is not None else 0.8
                circle = mpatches.Circle(
                    (cx, cy), TUBE_RADIUS,
                    facecolor=face, edgecolor=edge,
                    linewidth=lw, zorder=3,
                )
                self._ax.add_patch(circle)

                # シーケンス番号
                if owner is not None:
                    seq_no = self._sequences[owner].index((row, col)) + 1
                    self._ax.text(
                        cx, cy, str(seq_no),
                        ha="center", va="center",
                        fontsize=7, color="white",
                        fontweight="bold", zorder=4,
                    )

        # ---- パス矢印 ----------------------------------------------------
        for pid, seq in enumerate(self._sequences):
            color = PASS_COLORS[pid % len(PASS_COLORS)]
            for k in range(len(seq) - 1):
                r0, c0 = seq[k]
                r1, c1 = seq[k + 1]
                x0 = c0 + 0.5
                y0 = r0 + 0.5 + (stagger if c0 % 2 == 1 else 0.0)
                x1 = c1 + 0.5
                y1 = r1 + 0.5 + (stagger if c1 % 2 == 1 else 0.0)
                self._ax.annotate(
                    "",
                    xy=(x1, y1), xytext=(x0, y0),
                    arrowprops=dict(
                        arrowstyle="->",
                        color=color,
                        lw=1.5,
                        connectionstyle="arc3,rad=0.15",
                    ),
                    zorder=5,
                )

        # ---- 凡例 --------------------------------------------------------
        legend_patches = []
        for pid in range(len(self._sequences)):
            src = self._inlet_sources[pid]
            label = f"Pass {pid}"
            if src is not None:
                label += f" ← Pass {src}"
            if pid == self._current_pass:
                label += " [編集中]"
            legend_patches.append(
                mpatches.Patch(color=PASS_COLORS[pid % len(PASS_COLORS)], label=label)
            )
        if legend_patches:
            self._ax.legend(
                handles=legend_patches,
                loc="upper right", fontsize=7,
                framealpha=0.85,
            )

        # ---- 軸設定 -------------------------------------------------------
        arr_label = "千鳥配列" if self._tube.arrangement == "staggered" else "正方配列"
        self._ax.set_xlim(-0.3, nc + 0.3)
        self._ax.set_ylim(-0.3, nr + (0.8 if stagger > 0 else 0.3))
        self._ax.set_aspect("equal", adjustable="box")
        self._ax.set_xlabel("コラム (空気流れ方向 →)", fontsize=8)
        self._ax.set_ylabel("行 (row)", fontsize=8)
        self._ax.set_xticks([c + 0.5 for c in range(nc)])
        self._ax.set_xticklabels([str(c) for c in range(nc)], fontsize=7)
        self._ax.set_yticks([r + 0.5 for r in range(nr)])
        self._ax.set_yticklabels([str(r) for r in range(nr)], fontsize=7)
        self._ax.set_title(
            f"パスエディター ({arr_label}) — 左クリック: 追加/削除, 右クリック: 削除",
            fontsize=9,
        )
        self._ax.grid(True, alpha=0.2, zorder=0)
        self._fig.tight_layout()
        self._canvas.draw()
        self._update_summary()

    # ------------------------------------------------------------------
    # サマリー更新
    # ------------------------------------------------------------------
    def _update_summary(self) -> None:
        lines = []
        for pid, (seq, src) in enumerate(zip(self._sequences, self._inlet_sources)):
            src_str = f"← Pass {src}" if src is not None else "外部入口"
            seqstr = "→".join(f"({r},{c})" for r, c in seq) if seq else "(空)"
            lines.append(f"Pass {pid} [{src_str}]: {seqstr}")
        self._summary.setText("\n".join(lines))

    # ------------------------------------------------------------------
    # シグナル発行
    # ------------------------------------------------------------------
    def _emit(self) -> None:
        cfg = self.get_pass_config()
        if cfg is not None:
            self.pass_config_changed.emit(cfg)

    # ------------------------------------------------------------------
    # ヘルパー
    # ------------------------------------------------------------------
    def _refresh_pass_combo(self) -> None:
        self._cb_pass.blockSignals(True)
        self._cb_pass.clear()
        for i in range(len(self._sequences)):
            self._cb_pass.addItem(f"Pass {i}")
        self._cb_pass.setCurrentIndex(
            min(self._current_pass, len(self._sequences) - 1)
        )
        self._current_pass = self._cb_pass.currentIndex()
        self._cb_pass.blockSignals(False)
