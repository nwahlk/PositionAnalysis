"""投资组合理论计算模块 — 六大投资理念的量化实现"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd
import numpy as np

from pa.analyzer import (
    DepositAnalysis, FundAnalysis, StockAnalysis, WealthAnalysis,
)


# ── 数据结构 ──────────────────────────────────────────────

@dataclass
class RiskProfile:
    age: int = 40
    investment_horizon_years: int = 10
    risk_tolerance: str = "moderate"
    max_drawdown_tolerance: float = 0.15


@dataclass
class AssetClassTarget:
    equity_pct: float = 0.0
    fixed_income_pct: float = 0.0
    cash_like_pct: float = 0.0
    alternative_pct: float = 0.0


@dataclass
class CorrelationResult:
    matrix: pd.DataFrame = field(default_factory=pd.DataFrame)
    high_corr_pairs: list = field(default_factory=list)
    avg_correlation: float = 0.0


@dataclass
class RiskBudgetResult:
    asset_risk_contribution: dict = field(default_factory=dict)
    risk_parity_weights: dict = field(default_factory=dict)
    current_weights: dict = field(default_factory=dict)
    top_risk_contributors: list = field(default_factory=list)


@dataclass
class BenchmarkResult:
    benchmark_name: str = ""
    portfolio_return: float = 0.0
    benchmark_return: float = 0.0
    alpha: float = 0.0
    tracking_error: float | None = None


@dataclass
class ScenarioResult:
    scenario_name: str = ""
    estimated_return: float = 0.0
    estimated_drawdown: float = 0.0
    description: str = ""


@dataclass
class AllocationAdvice:
    saa_target: AssetClassTarget = field(default_factory=AssetClassTarget)
    saa_current: AssetClassTarget = field(default_factory=AssetClassTarget)
    saa_deviation: AssetClassTarget = field(default_factory=AssetClassTarget)
    correlation: CorrelationResult | None = None
    risk_budget: RiskBudgetResult | None = None
    benchmarks: list = field(default_factory=list)
    scenarios: list = field(default_factory=list)
    all_weather_score: float = 0.0
    rebalance_actions: list = field(default_factory=list)
    value_signals: list = field(default_factory=list)
    cost_warnings: list = field(default_factory=list)
    theory_summary: str = ""


# ── 资产分类 ──────────────────────────────────────────────

# 名称关键词 → 资产类别
_EQUITY_KEYWORDS = ["股票", "混合", "指数", "增强", "QDII", "沪深", "中证",
                    "创业板", "科创板", "恒生"]
_FIXED_INCOME_KEYWORDS = ["债券", "纯债", "信用", "利率债", "国债", "政金债"]
_CASH_KEYWORDS = ["货币", "理财", "存款", "现金"]
_ALT_KEYWORDS = ["商品", "黄金", "REITs", "原油", "能源"]


def classify_assets(
    funds: list[FundAnalysis],
    stocks: list[StockAnalysis],
    deposits: list[DepositAnalysis],
    wealth: list[WealthAnalysis],
) -> dict[str, list[tuple[str, str, float]]]:
    """将所有持仓分为 equity/fixed_income/cash_like/alternative 四类

    返回: {"equity": [(code, name, value), ...], ...}
    """
    result: dict[str, list[tuple[str, str, float]]] = {
        "equity": [], "fixed_income": [], "cash_like": [], "alternative": []
    }

    for f in funds:
        item = (f.code, f.name, f.current_value)
        category = _classify_fund(f.name)
        result[category].append(item)

    for s in stocks:
        result["equity"].append((s.code, s.name, s.current_value))

    for d in deposits:
        result["cash_like"].append(("", d.name, d.amount))

    for w in wealth:
        result["cash_like"].append(("", w.name, w.amount))

    return result


def _classify_fund(name: str) -> str:
    """按名称关键词分类基金"""
    for kw in _ALT_KEYWORDS:
        if kw in name:
            return "alternative"
    for kw in _FIXED_INCOME_KEYWORDS:
        if kw in name:
            return "fixed_income"
    for kw in _CASH_KEYWORDS:
        if kw in name:
            return "cash_like"
    return "equity"


# ── 战略资产配置 (SAA) ────────────────────────────────────

_SAA_BASE = {
    "conservative": (0.30, 0.40, 0.20, 0.10),
    "moderate": (0.50, 0.25, 0.15, 0.10),
    "aggressive": (0.70, 0.15, 0.10, 0.05),
}


def calc_saa_target(profile: RiskProfile) -> AssetClassTarget:
    """根据风险画像计算目标配置，年龄做微调"""
    base = _SAA_BASE.get(profile.risk_tolerance, _SAA_BASE["moderate"])
    eq, fi, cl, alt = base

    # 年龄调整：基准年龄 40，每大 1 岁权益 -1%，下限 20%，上限 70%
    age_adj = (profile.age - 40)
    eq = max(0.20, min(0.70, eq - age_adj * 0.01))

    total = eq + fi + cl + alt
    return AssetClassTarget(
        equity_pct=eq / total,
        fixed_income_pct=fi / total,
        cash_like_pct=cl / total,
        alternative_pct=alt / total,
    )


def calc_current_allocation(
    asset_classes: dict[str, list[tuple[str, str, float]]],
    total_value: float,
) -> AssetClassTarget:
    """计算当前实际配置比例"""
    if total_value <= 0:
        return AssetClassTarget()
    sums = {k: sum(v for _, _, v in vs) for k, vs in asset_classes.items()}
    return AssetClassTarget(
        equity_pct=sums.get("equity", 0) / total_value,
        fixed_income_pct=sums.get("fixed_income", 0) / total_value,
        cash_like_pct=sums.get("cash_like", 0) / total_value,
        alternative_pct=sums.get("alternative", 0) / total_value,
    )


def calc_saa_deviation(current: AssetClassTarget, target: AssetClassTarget) -> AssetClassTarget:
    return AssetClassTarget(
        equity_pct=current.equity_pct - target.equity_pct,
        fixed_income_pct=current.fixed_income_pct - target.fixed_income_pct,
        cash_like_pct=current.cash_like_pct - target.cash_like_pct,
        alternative_pct=current.alternative_pct - target.alternative_pct,
    )


# ── 相关性分析 (Markowitz) ─────────────────────────────────

def calc_correlation_matrix(
    nav_histories: dict[str, pd.Series],
    threshold: float = 0.80,
) -> CorrelationResult:
    """计算基金/股票日收益率相关矩阵，标记高相关对"""
    if len(nav_histories) < 2:
        return CorrelationResult()

    # 构造日收益率 DataFrame，自动对齐日期
    returns_df = pd.DataFrame(nav_histories).apply(pd.to_numeric, errors="coerce")
    returns_df = returns_df.pct_change(fill_method=None).dropna(how="all")
    if len(returns_df) < 20:
        return CorrelationResult()

    corr = returns_df.corr()

    # 找高相关对
    pairs = []
    names = list(corr.columns)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            c = corr.iloc[i, j]
            if abs(c) > threshold:
                pairs.append((names[i], names[j], round(float(c), 2)))

    # 平均相关系数（取绝对值后平均，排除自相关对角线）
    mask = np.triu(np.ones(corr.shape, dtype=bool), k=1)
    avg_corr = float(np.abs(corr.where(mask)).mean().mean()) if mask.any() else 0.0

    return CorrelationResult(
        matrix=corr,
        high_corr_pairs=sorted(pairs, key=lambda x: -abs(x[2])),
        avg_correlation=round(avg_corr, 2),
    )


# ── 风险预算 (Clarkson / Dalio) ───────────────────────────

def calc_risk_budget(
    nav_histories: dict[str, pd.Series],
    current_weights: dict[str, float],
) -> RiskBudgetResult:
    """逆波动率风险平价计算"""
    if len(nav_histories) < 2:
        return RiskBudgetResult()

    returns_df = pd.DataFrame(nav_histories).apply(pd.to_numeric, errors="coerce")
    returns_df = returns_df.pct_change(fill_method=None).dropna(how="all")
    if len(returns_df) < 20:
        return RiskBudgetResult()

    # 年化波动率
    vols = returns_df.std() * (252 ** 0.5)
    vols = vols.replace(0, float("inf"))

    # 逆波动率权重（风险平价近似解）
    inv_vol = 1.0 / vols
    rp_weights = inv_vol / inv_vol.sum()

    # 实际权重
    common = current_weights.keys() & vols.index
    if not common:
        return RiskBudgetResult()
    w = pd.Series({k: current_weights[k] for k in common})
    w = w / w.sum()

    # 协方差矩阵
    cov = returns_df[list(common)].cov()

    # 风险贡献 RC_i = w_i * (Cov @ w)_i / (w' @ Cov @ w)
    marginal = cov.dot(w)
    total_risk = w.dot(marginal)
    if total_risk <= 0:
        return RiskBudgetResult()

    rc = w * marginal / total_risk
    rc = rc / rc.sum()  # 归一化到百分比

    # 前 N 大风险贡献者
    top = sorted(rc.items(), key=lambda x: -x[1])[:5]

    return RiskBudgetResult(
        asset_risk_contribution={k: round(float(v), 3) for k, v in rc.items()},
        risk_parity_weights={k: round(float(v), 4) for k, v in rp_weights.items()},
        current_weights={k: round(float(current_weights.get(k, 0)), 4) for k in common},
        top_risk_contributors=[(name, round(pct * 100, 1)) for name, pct in top],
    )


# ── 基准对比 (Bogle) ─────────────────────────────────────

def calc_benchmark_comparison(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series,
    benchmark_name: str = "",
) -> BenchmarkResult:
    """组合 vs 基准的 Alpha 和跟踪误差"""
    if portfolio_returns.empty or benchmark_returns.empty:
        return BenchmarkResult(benchmark_name=benchmark_name)

    aligned = pd.concat([portfolio_returns, benchmark_returns], axis=1).dropna()
    if len(aligned) < 20:
        return BenchmarkResult(benchmark_name=benchmark_name)

    port_cum = float((1 + aligned.iloc[:, 0]).prod() - 1)
    bench_cum = float((1 + aligned.iloc[:, 1]).prod() - 1)
    alpha = port_cum - bench_cum
    tracking_error = float((aligned.iloc[:, 0] - aligned.iloc[:, 1]).std() * (252 ** 0.5))

    return BenchmarkResult(
        benchmark_name=benchmark_name,
        portfolio_return=port_cum,
        benchmark_return=bench_cum,
        alpha=round(alpha, 4),
        tracking_error=round(tracking_error, 4),
    )


# ── 情景分析 ─────────────────────────────────────────────

_SCENARIO_COEFFS = {
    "牛市": {"equity": 0.25, "fixed_income": -0.03, "cash_like": 0.01, "alternative": 0.10},
    "熊市": {"equity": -0.30, "fixed_income": 0.05, "cash_like": 0.00, "alternative": -0.05},
    "利率上行": {"equity": -0.10, "fixed_income": -0.08, "cash_like": 0.01, "alternative": 0.00},
    "通胀上行": {"equity": -0.05, "fixed_income": -0.05, "cash_like": -0.02, "alternative": 0.15},
    "通缩": {"equity": -0.15, "fixed_income": 0.10, "cash_like": 0.03, "alternative": -0.10},
}


def calc_scenario_analysis(
    asset_class_weights: dict[str, float],
    custom_coeffs: dict[str, dict[str, float]] | None = None,
) -> list[ScenarioResult]:
    """情景分析：各资产类别在不同经济环境下的预估表现"""
    coeffs = custom_coeffs or _SCENARIO_COEFFS
    results = []

    descriptions = {
        "牛市": "权益类资产受益最大，固收小幅回撤",
        "熊市": "权益类大幅下跌，固收提供缓冲",
        "利率上行": "股债双杀，现金类小幅受益",
        "通胀上行": "实物资产受益，股债承压",
        "通缩": "固收资产受益，权益和商品承压",
    }

    for name, impacts in coeffs.items():
        est_return = sum(
            asset_class_weights.get(cls, 0) * impacts.get(cls, 0)
            for cls in ["equity", "fixed_income", "cash_like", "alternative"]
        )
        # 回撤约等于负收益
        est_drawdown = abs(est_return) * 1.2 if est_return < 0 else 0
        results.append(ScenarioResult(
            scenario_name=name,
            estimated_return=round(est_return, 3),
            estimated_drawdown=round(est_drawdown, 3),
            description=descriptions.get(name, ""),
        ))

    return results


# ── 全天候评分 (Dalio) ───────────────────────────────────

def calc_all_weather_score(
    saa_deviation: AssetClassTarget,
    correlation: CorrelationResult | None,
    risk_budget: RiskBudgetResult | None,
) -> float:
    """全天候适配度 0~100"""
    # 1. SAA 偏差度（40 分）
    dev = sum(abs(getattr(saa_deviation, f)) for f in
            ["equity_pct", "fixed_income_pct", "cash_like_pct", "alternative_pct"])
    saa_score = max(0, 40 - dev * 200)  # 偏差 20% 扣满 40 分

    # 2. 分散质量（30 分）—— 平均相关系数越低越好
    if correlation and correlation.avg_correlation > 0:
        corr_score = max(0, 30 * (1 - correlation.avg_correlation))
    else:
        corr_score = 30  # 无数据给满分

    # 3. 风险均衡（30 分）—— 风险贡献越均匀越好
    if risk_budget and risk_budget.asset_risk_contribution:
        rcs = list(risk_budget.asset_risk_contribution.values())
        if rcs:
            # 理想：每个资产贡献 1/N
            ideal = 1.0 / len(rcs)
            # 实际分布与均匀分布的偏差
            risk_score = max(0, 30 * (1 - sum(abs(r - ideal) for r in rcs)))
        else:
            risk_score = 30
    else:
        risk_score = 30

    return round(min(100, saa_score + corr_score + risk_score), 1)


# ── 再平衡建议 ─────────────────────────────────────────────

def generate_rebalance_actions(
    saa_current: AssetClassTarget,
    saa_target: AssetClassTarget,
    total_value: float,
    threshold: float = 0.05,
) -> list[str]:
    """生成具体再平衡建议"""
    actions = []
    labels = {
        "equity_pct": "权益类",
        "fixed_income_pct": "固收类",
        "cash_like_pct": "现金类",
        "alternative_pct": "另类",
    }
    directions = {
        "equity_pct": "股票型/混合型基金",
        "fixed_income_pct": "债券型基金",
        "cash_like_pct": "货币基金/存款/理财",
        "alternative_pct": "商品/黄金",
    }

    for field, label in labels.items():
        current = getattr(saa_current, field)
        target = getattr(saa_target, field)
        diff = current - target
        if abs(diff) > threshold:
            amount = abs(diff) * total_value
            if diff > 0:
                actions.append(
                    f"{label}超配 {diff:.0%}（约 {_fmt_money(amount)}），"
                    f"建议减少{directions[field]}持仓"
                )
            else:
                actions.append(
                    f"{label}低配 {-diff:.0%}（约 {_fmt_money(amount)}），"
                    f"建议增加{directions[field]}配置"
                )

    if not actions:
        actions.append("当前配置与目标偏差在阈值以内，无需再平衡")

    return actions


# ── 价值信号 (Graham/Buffett) ────────────────────────────────

def generate_value_signals(
    funds: list[FundAnalysis],
    stocks: list[StockAnalysis],
) -> list[str]:
    """识别价值投资信号"""
    signals = []

    # 基金：排名靠后 + 近期下跌 = 恐慌区，可能是逆向买入机会
    for f in funds:
        if f.rank_pct > 75 and f.ret_3m and f.ret_3m < -0.10:
            signals.append(
                f"{f.name}（{f.code}）：同类排名后{100-f.rank_pct:.0f}%，"
                f"近3月下跌{abs(f.ret_3m)*100:.1f}%，可能处于恐慌区"
            )

    # 股票：PB 破净 + RSI 超卖
    for s in stocks:
        if s.pb is not None and s.pb < 1.0 and s.rsi is not None and s.rsi < 35:
            signals.append(
                f"{s.name}（{s.code}）：PB={s.pb:.2f} 破净，"
                f"RSI={s.rsi:.1f} 接近超卖，具备安全边际"
            )

    if not signals:
        signals.append("当前未发现明显的价值投资信号")

    return signals


# ── 成本效率提醒 (Bogle) ─────────────────────────────────

def generate_cost_warnings(
    funds: list[FundAnalysis],
    stock_pct: float,
) -> list[str]:
    """识别成本效率问题"""
    warnings = []

    active_count = sum(1 for f in funds if "指数" not in f.name)
    index_count = sum(1 for f in funds if "指数" in f.name)
    total = len(funds)

    if total > 0:
        active_ratio = active_count / total
        if active_ratio > 0.6:
            warnings.append(
                f"主动管理基金占比 {active_ratio:.0%}（{active_count}/{total} 只），"
                f"历史表明大部分主动基金长期跑输指数，考虑增加指数基金比例"
            )

    if stock_pct < 0.10 and total > 5:
        warnings.append("股票占比不足 10%，无法有效分散个股风险")

    # 高波动率基金过多
    high_vol = sum(1 for f in funds if f.volatility and f.volatility > 25)
    if high_vol > 3:
        warnings.append(
            f"{high_vol} 只基金年化波动率超过 25%，高波动侵蚀长期复利收益"
        )

    return warnings


# ── 工具函数 ────────────────────────────────────────────────

def _fmt_money(v: float) -> str:
    if v >= 10000:
        return f"{v/10000:,.2f}万"
    return f"{v:,.2f}"


# ── 顶层编排 ────────────────────────────────────────────────

def run_full_portfolio_analysis(
    funds: list[FundAnalysis],
    stocks: list[StockAnalysis],
    deposits: list[DepositAnalysis],
    wealth: list[WealthAnalysis],
    nav_histories: dict[str, pd.Series],
    price_histories: dict[str, pd.Series],
    profile: RiskProfile,
    benchmark_data: dict[str, pd.Series] | None,
    overview,  # PortfolioOverview
    config: dict | None = None,
) -> AllocationAdvice:
    """顶层编排：调用所有计算，返回完整资产配置建议"""
    advanced = (config or {}).get("advanced", {})
    corr_threshold = advanced.get("correlation_threshold", 0.80)
    rebalance_threshold = advanced.get("rebalance_threshold", 0.05)

    # 1. 资产分类
    asset_classes = classify_assets(funds, stocks, deposits, wealth)

    # 2. SAA
    saa_target = calc_saa_target(profile)
    saa_current = calc_current_allocation(asset_classes, overview.total_value)
    saa_deviation = calc_saa_deviation(saa_current, saa_target)

    # 3. 相关性
    # 合并基金和股票的历史数据（排除港股）
    nav_for_corr = {k: v for k, v in nav_histories.items() if not k.upper().startswith("H")}
    correlation = calc_correlation_matrix(nav_for_corr, corr_threshold)

    # 4. 风险预算（基于基金净值历史）
    fund_weights = {f.code: f.current_value for f in funds if f.current_value > 0}
    risk_budget = calc_risk_budget(nav_for_corr, fund_weights)

    # 5. 基准对比
    benchmarks = []
    if benchmark_data:
        # 构造组合日收益率序列（基于持仓净值）
        fund_returns = {}
        for f in funds:
            if f.code in nav_histories and not nav_histories[f.code].empty:
                fund_returns[f.code] = nav_histories[f.code].pct_change()
        if fund_returns:
            port_ret = pd.DataFrame(fund_returns).mean(axis=1)

        if "hs300" in benchmark_data and not benchmark_data["hs300"].empty:
            benchmarks.append(
                calc_benchmark_comparison(port_ret, benchmark_data["hs300"].pct_change(), "沪深300")
            )

    # 6. 情景分析
    scenarios = calc_scenario_analysis(
        {"equity": saa_current.equity_pct, "fixed_income": saa_current.fixed_income_pct,
         "cash_like": saa_current.cash_like_pct, "alternative": saa_current.alternative_pct}
    )

    # 7. 全天候评分
    all_weather = calc_all_weather_score(saa_deviation, correlation, risk_budget)

    # 8. 再平衡建议
    rebalance_actions = generate_rebalance_actions(
        saa_current, saa_target, overview.total_value, rebalance_threshold
    )

    # 9. 价值信号
    value_signals = generate_value_signals(funds, stocks)

    # 10. 成本警告
    cost_warnings = generate_cost_warnings(funds, overview.stock_pct)

    # 11. 综合评价
    theory_summary = _generate_theory_summary(
        saa_deviation, all_weather, correlation, rebalance_actions, benchmarks,
    )

    return AllocationAdvice(
        saa_target=saa_target,
        saa_current=saa_current,
        saa_deviation=saa_deviation,
        correlation=correlation,
        risk_budget=risk_budget,
        benchmarks=benchmarks,
        scenarios=scenarios,
        all_weather_score=all_weather,
        rebalance_actions=rebalance_actions,
        value_signals=value_signals,
        cost_warnings=cost_warnings,
        theory_summary=theory_summary,
    )


def _generate_theory_summary(
    saa_deviation: AssetClassTarget,
    all_weather: float,
    correlation: CorrelationResult | None,
    rebalance: list[str],
    benchmarks: list[BenchmarkResult],
) -> str:
    """生成综合评价文字"""
    parts = []

    # SAA 偏差
    total_dev = sum(abs(getattr(saa_deviation, f)) for f in
                    ["equity_pct", "fixed_income_pct", "cash_like_pct", "alternative_pct"])
    if total_dev > 0.15:
        parts.append(f"当前配置严重偏离目标（总偏差{total_dev:.0%}），建议优先再平衡")
    elif total_dev > 0.05:
        parts.append(f"当前配置与目标存在偏差（总偏差{total_dev:.0%}），建议择机再平衡")
    else:
        parts.append("当前配置接近目标配置")

    # 全天候评分
    if all_weather >= 70:
        parts.append(f"全天候适配度 {all_weather:.0f}/100，配置较为均衡")
    elif all_weather >= 50:
        parts.append(f"全天候适配度 {all_weather:.0f}/100，仍有改善空间")
    else:
        parts.append(
            f"全天候适配度仅 {all_weather:.0f}/100，"
            f"{'资产相关性偏高' if correlation and correlation.avg_correlation > 0.5 else '配置集中于单一经济环境'}"
        )

    # 基准对比
    if benchmarks:
        for b in benchmarks:
            if b.alpha > 0:
                parts.append(f"近3月跑赢{b.benchmark_name} {b.alpha*100:+.2f}%")
            else:
                parts.append(f"近3月跑输{b.benchmark_name} {abs(b.alpha)*100:.2f}%")

    return "；".join(parts)
