from dataclasses import dataclass


@dataclass(frozen=True)
class FluidProperties:
    name: str
    rho: float   # 密度 [kg/m³]
    cp: float    # 比熱 [J/kg·K]
    mu: float    # 粘度 [Pa·s]
    k: float     # 熱伝導率 [W/m·K]
    Pr: float    # プラントル数


# 定物性デフォルト値 (25°C付近)
AIR = FluidProperties(
    name="Air",
    rho=1.184,
    cp=1007.0,
    mu=1.849e-5,
    k=0.02551,
    Pr=0.7296,
)

WATER = FluidProperties(
    name="Water",
    rho=997.0,
    cp=4182.0,
    mu=8.9e-4,
    k=0.607,
    Pr=6.14,
)


@dataclass
class WaterInlet:
    T_in: float        # 入口水温 [°C]
    flow_rate: float   # 質量流量 [kg/s]


@dataclass
class AirCondition:
    T_in: float       # 入口空気温度 [°C] (全面一様)
    velocity: float   # 前面風速 [m/s]
