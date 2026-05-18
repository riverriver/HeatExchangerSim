# 熱交換器シミュレーター 設計仕様書

**バージョン**: 1.0  
**作成日**: 2026-05-18  
**対象**: 直交流・フィンアンドチューブ 水-空気熱交換器

---

## 1. シミュレーション前提条件

| 項目 | 設定 |
|------|------|
| 流れ形式 | 直交流 (空気: 水平貫流, 水: 管内流) |
| 熱交換器種別 | フィンアンドチューブ |
| 流体物性 | 定物性 (const properties) |
| 空気入口温度分布 | 一様分布 |
| パス接続 | 直列・並列パスを許容 |
| 管配列 | 千鳥配列 / 正方配列 (切り替え可) |
| 空気横方向混合 | 簡易近似 (後述) |

---

## 2. プロジェクト構成

```
HeatExchangerSim/
├── design_spec.md          # 本ファイル
├── main.py                 # エントリーポイント
├── domain/
│   ├── __init__.py
│   ├── geometry.py         # 管・フィン形状
│   ├── fluid.py            # 流体物性 (定物性)
│   ├── pass_config.py      # パス接続グラフ
│   ├── correlations.py     # 熱伝達相関式・フィン効率
│   └── solver.py           # セル毎差分ソルバー
├── gui/
│   ├── __init__.py
│   ├── main_window.py      # メインウィンドウ
│   ├── param_panel.py      # パラメータ入力パネル
│   ├── grid_view.py        # 管配置+温度カラーマップ
│   ├── pass_editor.py      # パス接続エディター
│   └── result_panel.py     # 結果表示パネル
└── requirements.txt
```

---

## 3. コアオブジェクト仕様

### 3-1. TubeGeometry

```python
@dataclass
class TubeGeometry:
    do: float           # 管外径 [m]
    di: float           # 管内径 [m]
    length: float       # 管長さ (フィン幅方向) [m]
    Sl: float           # 縦ピッチ: 空気流れ方向の管間隔 [m]
    St: float           # 横ピッチ: 管列方向の管間隔 [m]
    n_rows: int         # 空気流れ方向の段数 (row方向)
    n_cols: int         # 管列数 (col方向)
    arrangement: Literal["staggered", "inline"]
```

### 3-2. FinGeometry

```python
@dataclass
class FinGeometry:
    pitch: float        # フィンピッチ [m]
    thickness: float    # フィン厚さ [m]
    k_fin: float        # フィン材料熱伝導率 [W/m·K]  (例: アルミ=205)
```

### 3-3. FluidProperties (定物性)

```python
@dataclass
class FluidProperties:
    name: str
    rho: float          # 密度 [kg/m³]
    cp: float           # 比熱 [J/kg·K]
    mu: float           # 粘度 [Pa·s]
    k: float            # 熱伝導率 [W/m·K]
    Pr: float           # プラントル数

# デフォルト値
AIR_DEFAULT = FluidProperties(
    name="Air", rho=1.2, cp=1006, mu=1.81e-5, k=0.0257, Pr=0.713
)
WATER_DEFAULT = FluidProperties(
    name="Water", rho=998, cp=4182, mu=1.002e-3, k=0.598, Pr=7.01
)
```

### 3-4. 境界条件

```python
@dataclass
class WaterInlet:
    T_in: float         # 入口水温 [°C]
    flow_rate: float    # 質量流量 [kg/s]

@dataclass
class AirCondition:
    T_in: float         # 入口空気温度 [°C] (全面一様)
    velocity: float     # 前面風速 [m/s]
```

---

## 4. パス接続モデル

### 4-1. 概念

チューブグリッドは `(row, col)` の2Dインデックスで管理する。  
パスとは「水が流れる管の順序付きリスト」であり、複数のパスが並列または直列に接続できる。

```
TubeGrid: n_rows × n_cols の2D管配置

パスの種類:
  - 直列パス: パスAの出口 → パスBの入口
  - 並列パス: 同じ入口水条件から複数パスに分岐
```

### 4-2. PassConfiguration

```python
@dataclass
class Pass:
    pass_id: int
    tube_sequence: list[tuple[int, int]]   # [(row, col), ...] 水の流れ順
    inlet_source: int | None               # None=外部入口, int=前段pass_id

@dataclass
class PassConfiguration:
    passes: list[Pass]
    # 並列: 複数のPassがinlet_source=None → 同じWaterInletを流量で分配
    # 直列: PassBのinlet_source=PassAのpass_id

    def flow_rate_per_pass(self, total_flow: float) -> dict[int, float]:
        """並列パス数で均等分配"""
        parallel_roots = [p for p in self.passes if p.inlet_source is None]
        q_each = total_flow / len(parallel_roots)
        # 直列接続先は同じ流量を引き継ぐ
        ...
```

### 4-3. パス接続例

```
例1: 2並列 × 各2直列 (計4パス, 4列×4行グリッド)

  Pass0(並列A): (0,0)→(1,0)→(2,0)→(3,0)  [1列目を下に流れる]
  Pass1(直列@Pass0): (0,1)→(1,1)→(2,1)→(3,1)  [2列目、Pass0の出口水温を引き継ぐ]
  Pass2(並列B): (0,2)→(1,2)→(2,2)→(3,2)
  Pass3(直列@Pass2): (0,3)→(1,3)→(2,3)→(3,3)

  水の流れ: 外部入口 → [Pass0 → Pass1] 並列 [Pass2 → Pass3] → 出口
```

---

## 5. 計算アルゴリズム

### 5-1. グリッド分割

熱交換器を `n_rows × n_cols` のセルグリッドに分割する。

```
空気流れ方向 →  (col: 0 → n_cols-1)
         col=0    col=1    col=2  ...
row=0  [セル00] [セル01] [セル02]
row=1  [セル10] [セル11] [セル12]
row=2  [セル20] [セル21] [セル22]
```

- 各セルに管1本が対応
- 空気は col 方向に左から右へ流れる
- 各セルの空気入口温度 = 前のセル(col-1)の空気出口温度

### 5-2. 空気側熱伝達率 (correlations.py)

**正方配列 (inline)**:
```
McQuiston相関式を使用
h_air = f(Re_Dh, Pr, geometry)
```

**千鳥配列 (staggered)**:
```
Chang & Wang (1997) 相関式を使用
j = 0.049 · Re_Dc^(-0.27) · (Fp/Dc)^(-0.14) · (Fp/Ll)^(-0.29) · ...
h_air = j · G · cp_air / Pr^(2/3)
```

### 5-3. フィン効率

```
m = sqrt(2 · h_air / (k_fin · t_fin))
L_eff = (St/2 - do/2) · (1 + 0.35 · ln(St/2 / (do/2)))   # 等価フィン高さ
η_fin = tanh(m · L_eff) / (m · L_eff)
η_o = 1 - (A_fin / A_total) · (1 - η_fin)                 # 総合表面効率
```

### 5-4. 水側熱伝達率

```
Re_water = ρ_w · u_w · di / μ_w

Re > 10000 (乱流):  Gnielinski相関
  Nu = (f/8)(Re-1000)Pr / [1 + 12.7√(f/8)(Pr^(2/3)-1)]
  f = (0.790 ln(Re) - 1.64)^(-2)

Re < 2300 (層流):  Nu = 3.66 (一定熱流束境界条件)

h_water = Nu · k_water / di
```

### 5-5. セル単位の熱計算 (ε-NTU法)

```python
def solve_cell(T_air_in, T_water_in, UA, m_dot_air_cell, m_dot_water):
    C_air   = m_dot_air_cell * cp_air
    C_water = m_dot_water    * cp_water
    C_min   = min(C_air, C_water)
    C_max   = max(C_air, C_water)
    C_r     = C_min / C_max
    NTU     = UA / C_min

    # 直交流・両流体非混合のε相関 (Incropera 式)
    ε = 1 - exp((NTU**0.22 / C_r) * (exp(-C_r * NTU**0.78) - 1))

    Q         = ε * C_min * (T_water_in - T_air_in)
    T_air_out   = T_air_in   + Q / C_air
    T_water_out = T_water_in - Q / C_water
    return T_air_out, T_water_out, Q
```

セルのUA:
```
UA_cell = 1 / (1/(η_o · h_air · A_air_cell) + R_wall + 1/(h_water · A_water_cell))

A_air_cell   = η_o · (A_fin_cell + A_bare_cell)  # セル空気側有効伝熱面積
A_water_cell = π · di · length                   # セル水側伝熱面積
R_wall       = ln(do/di) / (2π · k_tube · length)
```

### 5-6. 千鳥配列における空気横方向混合

千鳥配列では管がコラム毎にSt/2ずつオフセットするため、前コラムで熱交換した空気が
次コラムの管に「どこから到着するか」の接続モデルが精度を左右する。

以下の2手法を実装し、`LateralMixingMode` 列挙型でフラグ切り替えを行う。

```python
class LateralMixingMode(Enum):
    NONE   = "none"    # 正方配列用（混合なし）
    SIMPLE = "simple"  # Approach A: 加重平均
    STREAM = "stream"  # Approach B: ストリーム分割 (推奨デフォルト)
```

---

#### Approach A — 単純加重平均 (SIMPLE)

各コラム通過後、全行に一律で加重平均を適用する経験的近似。

```
T_mixed[j] = α·T[j] + β·(T[j-1]+T[j+1])/2     (内部行)
T_mixed[0]       = α·T[0]     + β·T[1]           (上端)
T_mixed[Nrow-1]  = α·T[Nrow-1]+ β·T[Nrow-2]     (下端)

係数: α=0.6, β=0.4 (経験値、要調整)
```

問題点: 千鳥のオフセット方向を無視し、α/β に物理的根拠がない。

---

#### Approach B — ストリーム分割法 (STREAM) ★推奨デフォルト

千鳥の幾何学的接続を忠実に反映した手法。パラメータ調整不要。

**考え方**:  
奇数コラムの管 j は、偶数コラムの管 j と管 j+1 の中間に位置する。  
→ 両管から出た空気が 50/50 で管 j に流入する。  
偶数・奇数コラムで混合方向が交互に切り替わる。

```
偶 → 奇コラム (管が下に半ピッチ移動):
  T_in[j, k+1] = 0.5*(T_out[j, k] + T_out[j+1, k])   j = 0,...,Nrow-2
  T_in[Nrow-1, k+1] = T_out[Nrow-1, k]                (下端境界: 片側のみ)

奇 → 偶コラム (管が上に半ピッチ移動):
  T_in[j, k+1] = 0.5*(T_out[j-1, k] + T_out[j, k])   j = 1,...,Nrow-1
  T_in[0, k+1] = T_out[0, k]                           (上端境界: 片側のみ)
```

**挙動の違い（具体例: Nrow=4, T_out=[30,40,50,60]°C）**:

```
Approach A (加重平均):
  T_mixed = [34, 38, 48, 57]  ← 全行に同じ操作、方向性なし

Approach B (偶→奇, ストリーム分割):
  T_in = [35, 45, 55, 60]    ← 温度分布が下にシフト (物理に対応)
```

---

#### 比較表

| 比較項目 | A: 加重平均 | B: ストリーム分割 |
|----------|------------|-----------------|
| 物理的根拠 | なし（経験係数） | 幾何学的導出 |
| 調整パラメータ | α, β (要調整) | なし |
| 千鳥方向性の表現 | 無視 | 交互に正確に再現 |
| 端部境界条件 | 任意近似 | 自然に決定 |
| 計算コスト | O(Nrow) | O(Nrow) |
| 実装難度 | 低 | 低〜中 |
| 推奨用途 | デバッグ・比較用 | 工学計算 (デフォルト) |

正方配列では横方向混合なし (NONE)。

### 5-7. メインソルバーループ

```
入力:
  - TubeGeometry, FinGeometry
  - FluidProperties (air, water)
  - AirCondition (T_in, velocity)
  - WaterInlet (T_in, flow_rate)
  - PassConfiguration

処理:
1. 空気側・水側の熱伝達率を事前計算 (定物性なので一度だけ)
2. セルUA行列を構築 (n_rows × n_cols)
3. 空気温度行列 T_air[row, col] を T_in_air で初期化
4. PassConfiguration に従い、パスを解析順に並べる
   (直列依存関係のトポロジカルソート)

5. for each pass (トポロジカル順):
     T_water = pass の入口水温 (外部入口 or 前段パス出口)
     m_dot   = pass の流量
     for (row, col) in pass.tube_sequence:
         T_air_out, T_water, Q = solve_cell(T_air[row, col], T_water, ...)
         T_air[row, col+1] += T_air_out  # 次列への寄与 (後で平均化)
         Q_total += Q

   if arrangement == "staggered":
       T_air[:, col+1] = apply_lateral_mixing(T_air[:, col+1])

6. 出力:
   - Q_total [W]
   - T_air_out[row, col] 行列 (空気出口温度分布)
   - T_water_out per pass (各パスの出口水温)
   - Q[row, col] 行列 (局所熱交換量分布)
```

---

## 6. GUI仕様

### 6-1. 全体レイアウト

```
┌──────────────────────────────────────────────────────────────────┐
│ Menu: [File]  [Simulation]  [View]                               │
├─────────────────┬────────────────────────────────────────────────┤
│ Parameters      │  [Tab: Grid View] [Tab: Pass Editor]           │
│ Panel           │                                                │
│                 │  Grid View:                                    │
│ ▼ Geometry      │    空気→→→→→→→→→→→→→→→→         │
│   管外径        │   ┌────┬────┬────┬────┐        │
│   管内径        │   │ ○  │ ○  │ ○  │ ○  │        │
│   管長さ        │   ├────┼────┼────┼────┤        │
│   縦/横ピッチ   │   │  ○ │  ○ │  ○ │  ○ │ ←千鳥  │
│   段数/列数     │   ├────┼────┼────┼────┤        │
│   配列: [▼]    │   │ ○  │ ○  │ ○  │ ○  │        │
│                 │   └────┴────┴────┴────┘        │
│ ▼ Fin           │    管: 水温カラーマップ                        │
│   フィンピッチ  │    セル背景: 空気温度カラーマップ              │
│   フィン厚さ    │                                                │
│   熱伝導率      │  Pass Editor:                                  │
│                 │    クリックで管を選択、ドラッグで接続順を設定   │
│ ▼ Water         │    色分けでパスを識別                          │
│   入口温度      │    並列/直列トグルボタン                       │
│   流量          │                                                │
│                 ├────────────────────────────────────────────────┤
│ ▼ Air           │  Results          │  Charts                    │
│   入口温度      │  Q_total: 8.5 kW  │  [空気出口温度 heatmap]   │
│   前面風速      │  効率ε: 0.72      │  [各パス水温プロファイル] │
│                 │  平均ΔT_air: 18℃ │  [局所Q分布]              │
│ [▶ Run]         │  水出口温度: 42℃  │                            │
└─────────────────┴────────────────────────────────────────────────┘
```

### 6-2. Grid View (grid_view.py)

- matplotlib `imshow` で空気温度分布をカラーマップ表示
- 管位置に円を描画し、水温で色付け (別カラースケール)
- 千鳥/正方配列に応じて管の座標をオフセット
- カラーバーを右端に表示
- ホバーで (row, col) の局所値をツールチップ表示

### 6-3. Pass Editor (pass_editor.py)

- 管グリッドをクリックして選択、複数選択で接続順を決定
- パス毎に色を割り当て (Pass0=青, Pass1=赤, ...)
- 矢印で水の流れ方向を表示
- ボタン: [新規パス] [接続] [並列設定] [クリア]
- 保存するとPassConfigurationオブジェクトに変換

### 6-4. Result Panel (result_panel.py)

| 表示項目 | 内容 |
|----------|------|
| Q_total | 総熱交換量 [kW] |
| 効率ε | Q_total / Q_max |
| 空気 ΔT (平均) | 空気の平均温度上昇 [°C] |
| 水出口温度 (各パス) | 各パス出口水温 [°C] |
| 空気出口温度分布 | heatmap (matplotlib) |
| 水温プロファイル | 折れ線グラフ (管順序 vs 水温) |
| 局所Q分布 | heatmap (Q[row, col]) |

---

## 7. 技術スタック

| 要素 | 採用 |
|------|------|
| GUI フレームワーク | PyQt6 |
| 可視化 | matplotlib (PyQt6 backend に埋め込み) |
| 計算 | numpy |
| データ構造 | dataclasses (標準ライブラリ) |
| Pythonバージョン | 3.11以上 |

```
requirements.txt:
PyQt6>=6.6
matplotlib>=3.8
numpy>=1.26
```

---

## 8. 実装フェーズ

### Phase 1: ドメイン計算コア
- [ ] `geometry.py`: TubeGeometry, FinGeometry
- [ ] `fluid.py`: FluidProperties (定物性定数)
- [ ] `correlations.py`: h_air, h_water, η_fin, UA_cell
- [ ] `pass_config.py`: Pass, PassConfiguration, トポロジカルソート
- [ ] `solver.py`: solve_cell, メインソルバーループ
- [ ] 単体テスト: 既知解との照合

### Phase 2: 基本GUI
- [ ] `main_window.py`: ウィンドウ骨格, タブ構成
- [ ] `param_panel.py`: パラメータ入力フォーム
- [ ] `grid_view.py`: 管配置 + 空気温度 heatmap
- [ ] `result_panel.py`: 数値結果 + チャート

### Phase 3: パスエディター
- [ ] `pass_editor.py`: インタラクティブな管接続編集
- [ ] 並列パス対応
- [ ] PassConfiguration ↔ GUI の双方向同期

### Phase 4: 精度向上・ユーザビリティ
- [ ] 千鳥配列の横方向混合係数の妥当性確認
- [ ] 入力バリデーション・エラーメッセージ
- [ ] 設定のファイル保存/読み込み (JSON)
- [ ] パラメトリックスイープ機能

---

## 9. 設計上の決定事項と根拠

| 決定 | 内容 | 根拠 |
|------|------|------|
| 定物性 | 温度依存性なし | 実装簡素化。実用範囲 (水0-80°C, 空気10-60°C) で誤差5%以内 |
| ε-NTU (直交流非混合式) | Incropera 式を各セルに適用 | 直交流セルへの局所適用で精度と実装容易性を両立 |
| 千鳥混合近似 α=0.6, β=0.4 | 列通過後に加重平均 | 厳密CFDより大幅に簡易。実験相関式との併用で実用精度を確保 |
| 並列パス: 均等流量分配 | 並列パス間で流量を均等に分割 | ポンプ特性・管抵抗は非対象。将来拡張の余地あり |
| PyQt6 + matplotlib | GUI + 可視化 | Pythonエコシステム内で最も実績のある組み合わせ |
