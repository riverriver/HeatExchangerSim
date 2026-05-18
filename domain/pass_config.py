"""
パス接続モデル

用語:
  Pass       : 水が流れる管の順序付きリスト
  inlet_source: None=外部水入口, int=前段パスのpass_id (直列接続)
  並列パス   : inlet_source=None のパスが複数 → 総流量を均等分配
  直列接続   : PassB.inlet_source = PassA.pass_id
"""

from __future__ import annotations
from dataclasses import dataclass, field


TubeIndex = tuple[int, int]  # (row, col)


@dataclass
class Pass:
    pass_id: int
    tube_sequence: list[TubeIndex]   # 水が流れる順序
    inlet_source: int | None = None  # None=外部入口, int=前段pass_id


@dataclass
class PassConfiguration:
    passes: list[Pass]

    # ------------------------------------------------------------------
    # バリデーション
    # ------------------------------------------------------------------
    def __post_init__(self) -> None:
        ids = {p.pass_id for p in self.passes}
        for p in self.passes:
            if p.inlet_source is not None and p.inlet_source not in ids:
                raise ValueError(
                    f"Pass {p.pass_id}: inlet_source={p.inlet_source} は存在しない pass_id"
                )
        if not self._root_passes():
            raise ValueError("inlet_source=None のパス (外部入口) が存在しません")
        # 循環参照チェック
        self._topological_order()

    # ------------------------------------------------------------------
    # 並列ルートパス (外部水入口を持つパス)
    # ------------------------------------------------------------------
    def _root_passes(self) -> list[Pass]:
        return [p for p in self.passes if p.inlet_source is None]

    # ------------------------------------------------------------------
    # 流量分配
    # 並列ルートパスの数で均等分配し、直列先は同流量を引き継ぐ
    # ------------------------------------------------------------------
    def flow_rate_per_pass(self, total_flow: float) -> dict[int, float]:
        n_parallel = len(self._root_passes())
        q_each = total_flow / n_parallel

        result: dict[int, float] = {}
        for order in self._topological_order():
            p = self._pass_by_id(order)
            if p.inlet_source is None:
                result[p.pass_id] = q_each
            else:
                result[p.pass_id] = result[p.inlet_source]
        return result

    # ------------------------------------------------------------------
    # トポロジカルソート (直列依存関係を解決)
    # 返り値: pass_id のリスト (解析順)
    # ------------------------------------------------------------------
    def _topological_order(self) -> list[int]:
        # Kahn's algorithm
        in_degree: dict[int, int] = {p.pass_id: 0 for p in self.passes}
        children: dict[int, list[int]] = {p.pass_id: [] for p in self.passes}

        for p in self.passes:
            if p.inlet_source is not None:
                in_degree[p.pass_id] += 1
                children[p.inlet_source].append(p.pass_id)

        queue = [pid for pid, deg in in_degree.items() if deg == 0]
        order: list[int] = []
        while queue:
            pid = queue.pop(0)
            order.append(pid)
            for child in children[pid]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        if len(order) != len(self.passes):
            raise ValueError("パス接続に循環参照があります")
        return order

    def _pass_by_id(self, pass_id: int) -> Pass:
        for p in self.passes:
            if p.pass_id == pass_id:
                return p
        raise KeyError(pass_id)

    # ------------------------------------------------------------------
    # 公開インターフェース
    # ------------------------------------------------------------------
    def sorted_passes(self) -> list[Pass]:
        """直列依存関係を解決した解析順のパスリスト"""
        return [self._pass_by_id(pid) for pid in self._topological_order()]

    def all_tube_indices(self) -> set[TubeIndex]:
        indices: set[TubeIndex] = set()
        for p in self.passes:
            indices.update(p.tube_sequence)
        return indices


# ------------------------------------------------------------------
# ファクトリ関数 (よく使うパターン)
# ------------------------------------------------------------------

def make_serpentine(n_rows: int, n_cols: int) -> PassConfiguration:
    """
    蛇行1パス: 全管を1本のパスに直列接続
    (row0,col0)→(row1,col0)→...→(rowN,col0)→(row0,col1)→...
    """
    sequence = [
        (row, col)
        for col in range(n_cols)
        for row in (range(n_rows) if col % 2 == 0 else range(n_rows - 1, -1, -1))
    ]
    return PassConfiguration(passes=[Pass(pass_id=0, tube_sequence=sequence)])


def make_parallel_passes(n_rows: int, n_cols: int, n_passes: int) -> PassConfiguration:
    """
    n_passes 本の並列パス。各パスが n_cols/n_passes 列ずつ担当する。
    n_cols は n_passes の倍数であること。
    """
    if n_cols % n_passes != 0:
        raise ValueError("n_cols は n_passes の倍数である必要があります")
    cols_per_pass = n_cols // n_passes
    passes = []
    for pid in range(n_passes):
        col_start = pid * cols_per_pass
        seq = [
            (row, col)
            for col in range(col_start, col_start + cols_per_pass)
            for row in range(n_rows)
        ]
        passes.append(Pass(pass_id=pid, tube_sequence=seq, inlet_source=None))
    return PassConfiguration(passes=passes)
