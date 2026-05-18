"""
熱伝達相関式・フィン効率・セルUA計算

空気側: Chang & Wang (1997) [千鳥], McQuiston (1978) [正方]
水側:   Gnielinski (乱流), Nu=3.66 (層流)
フィン効率: Schmidt近似法
"""

import math
from .geometry import TubeGeometry, FinGeometry
from .fluid import FluidProperties


# ---------------------------------------------------------------------------
# 空気側熱伝達率
# ---------------------------------------------------------------------------

def h_air_staggered(
    tube: TubeGeometry,
    fin: FinGeometry,
    air: FluidProperties,
    velocity_face: float,
) -> float:
    """
    千鳥配列の空気側熱伝達率 [W/m²·K]
    Chang & Wang (1997) ルーバーフィン相関の平滑フィン近似版。
    平滑プレートフィンに対してはコルバーン j 因子で評価する。
    """
    # 最小断面での最大速度
    sigma = 1 - math.pi * tube.do / (4 * tube.St)  # 正面面積比 (簡易)
    u_max = velocity_face / sigma

    # 水力直径 (プレートフィン)
    A_fin_per_tube = 2 * (tube.St * tube.Sl - math.pi * tube.do**2 / 4)
    A_bare_per_tube = math.pi * tube.do * (fin.pitch - fin.thickness)
    A_total_per_tube = A_fin_per_tube + A_bare_per_tube
    Dh = 4 * (tube.St - tube.do) * (fin.pitch - fin.thickness) / (
        2 * ((tube.St - tube.do) + (fin.pitch - fin.thickness))
    )

    Re_Dh = air.rho * u_max * Dh / air.mu

    # Colburn j 因子 (平滑プレートフィン, 千鳥配列)
    # Chang & Wang 簡易式: j ≈ 0.086 Re^(-0.45)
    j = 0.086 * Re_Dh**(-0.45)

    h = j * air.rho * u_max * air.cp / air.Pr ** (2 / 3)
    return max(h, 1.0)  # 下限ガード


def h_air_inline(
    tube: TubeGeometry,
    fin: FinGeometry,
    air: FluidProperties,
    velocity_face: float,
) -> float:
    """
    正方配列の空気側熱伝達率 [W/m²·K]
    McQuiston (1978) 相関の簡易形。
    """
    sigma = 1 - math.pi * tube.do / (4 * tube.St)
    u_max = velocity_face / sigma

    Dh = 4 * (tube.St - tube.do) * (fin.pitch - fin.thickness) / (
        2 * ((tube.St - tube.do) + (fin.pitch - fin.thickness))
    )
    Re_Dh = air.rho * u_max * Dh / air.mu

    # McQuiston 簡易 j 因子 (正方配列)
    j = 0.0675 * Re_Dh**(-0.40)

    h = j * air.rho * u_max * air.cp / air.Pr ** (2 / 3)
    return max(h, 1.0)


def h_air(
    tube: TubeGeometry,
    fin: FinGeometry,
    air: FluidProperties,
    velocity_face: float,
) -> float:
    if tube.arrangement == "staggered":
        return h_air_staggered(tube, fin, air, velocity_face)
    return h_air_inline(tube, fin, air, velocity_face)


# ---------------------------------------------------------------------------
# フィン効率・総合表面効率 (Schmidt近似)
# ---------------------------------------------------------------------------

def fin_efficiency(
    tube: TubeGeometry,
    fin: FinGeometry,
    h: float,
) -> tuple[float, float]:
    """
    フィン効率 η_fin と総合表面効率 η_o を返す。
    Schmidt近似による等価フィン高さを使用。

    Returns
    -------
    η_fin : float
    η_o   : float
    """
    r_o = tube.do / 2
    r_eq = tube.St / 2  # 等価外半径 (正方近似)

    # Schmidt 等価フィン半径比
    phi = (r_eq / r_o - 1) * (1 + 0.35 * math.log(r_eq / r_o))
    L_eff = phi * r_o  # 等価フィン高さ

    m = math.sqrt(2 * h / (fin.k_fin * fin.thickness))
    mL = m * L_eff

    if mL < 1e-6:
        eta_fin = 1.0
    else:
        eta_fin = math.tanh(mL) / mL

    # フィン面積比
    A_fin = 2 * (tube.St * tube.Sl - math.pi * r_o**2)
    A_bare = math.pi * tube.do * (fin.pitch - fin.thickness)
    A_total = A_fin + A_bare

    eta_o = 1 - (A_fin / A_total) * (1 - eta_fin)
    return eta_fin, eta_o


# ---------------------------------------------------------------------------
# 水側熱伝達率
# ---------------------------------------------------------------------------

def h_water(
    tube: TubeGeometry,
    water: FluidProperties,
    flow_rate_per_tube: float,
) -> float:
    """
    管内水側熱伝達率 [W/m²·K]
    乱流: Gnielinski, 層流: Nu=3.66
    """
    A_cross = math.pi * tube.di**2 / 4
    u = flow_rate_per_tube / (water.rho * A_cross)
    Re = water.rho * u * tube.di / water.mu

    if Re > 10000:
        # Gnielinski
        f = (0.790 * math.log(Re) - 1.64) ** (-2)
        Nu = (f / 8) * (Re - 1000) * water.Pr / (
            1 + 12.7 * math.sqrt(f / 8) * (water.Pr ** (2 / 3) - 1)
        )
    elif Re < 2300:
        Nu = 3.66  # 層流・一定壁温
    else:
        # 遷移域: 線形補間
        t = (Re - 2300) / (10000 - 2300)
        f = (0.790 * math.log(10000) - 1.64) ** (-2)
        Nu_turb = (f / 8) * (10000 - 1000) * water.Pr / (
            1 + 12.7 * math.sqrt(f / 8) * (water.Pr ** (2 / 3) - 1)
        )
        Nu = 3.66 * (1 - t) + Nu_turb * t

    return Nu * water.k / tube.di


# ---------------------------------------------------------------------------
# セル UA
# ---------------------------------------------------------------------------

def cell_UA(
    tube: TubeGeometry,
    fin: FinGeometry,
    air: FluidProperties,
    water: FluidProperties,
    velocity_face: float,
    flow_rate_per_tube: float,
) -> float:
    """
    1セル (管1本分) の総括熱通過率 UA [W/K]
    """
    h_a = h_air(tube, fin, air, velocity_face)
    _, eta_o = fin_efficiency(tube, fin, h_a)
    h_w = h_water(tube, water, flow_rate_per_tube)

    # セル伝熱面積
    A_fin = 2 * (tube.St * tube.Sl - math.pi * (tube.do / 2) ** 2)
    A_bare = math.pi * tube.do * (fin.pitch - fin.thickness)
    A_air = eta_o * (A_fin + A_bare)

    A_water = math.pi * tube.di * tube.length

    # 管壁熱抵抗
    R_wall = math.log(tube.do / tube.di) / (2 * math.pi * tube.k_tube * tube.length)

    R_total = 1 / (eta_o * h_a * A_air) + R_wall + 1 / (h_w * A_water)
    return 1 / R_total
