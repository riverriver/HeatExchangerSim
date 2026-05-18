from dataclasses import dataclass
from typing import Literal
import math


@dataclass
class TubeGeometry:
    do: float                                    # 管外径 [m]
    di: float                                    # 管内径 [m]
    length: float                                # 管長さ (フィン幅方向) [m]
    Sl: float                                    # 縦ピッチ: 空気流れ方向 [m]
    St: float                                    # 横ピッチ: 管列方向 [m]
    n_rows: int                                  # 空気流れ方向の段数
    n_cols: int                                  # 管列数
    arrangement: Literal["staggered", "inline"]  # 千鳥 or 正方

    def __post_init__(self) -> None:
        assert self.do > self.di > 0
        assert self.Sl > self.do and self.St > self.do
        assert self.n_rows >= 1 and self.n_cols >= 1

    @property
    def Sd(self) -> float:
        """千鳥配列の対角ピッチ [m]"""
        return math.sqrt(self.Sl**2 + (self.St / 2) ** 2)

    @property
    def k_tube(self) -> float:
        """銅管のデフォルト熱伝導率 [W/m·K]"""
        return 385.0


@dataclass
class FinGeometry:
    pitch: float      # フィンピッチ [m]
    thickness: float  # フィン厚さ [m]
    k_fin: float      # フィン材料熱伝導率 [W/m·K]  (アルミ≈205, 銅≈385)

    def __post_init__(self) -> None:
        assert self.pitch > self.thickness > 0
        assert self.k_fin > 0
