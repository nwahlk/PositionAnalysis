"""核心分析引擎 - 盈亏计算、风险指标、建议评分"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from pa.fetcher import FundMarketData, StockMarketData
from pa.parser import (
    DepositPosition, FundPosition, PositionSnapshot,
    StockPosition, WealthPosition,
)


@dataclass
class FundAnalysis:
    """基金分析结果"""
    code: str
    name: str
    shares: float
    cost_nav: float | None         # None 表示未知成本
    current_nav: float
    cost_value: float              # 成本总额
    current_value: float           # 当前总额
    profit: float                  # 盈亏金额
    profit_pct: float              # 盈亏比例
    nav_change_pct: float          # 日涨跌幅
    rank_pct: float                # 同类排名百分比
    sharpe_ratio: float | None     # 夏普比率
    max_drawdown: float | None     # 最大回撤
    score: int                     # 综合评分
    recommendation: str            # 买入/持有/卖出
    reason: str = ""               # 建议理由
    volatility: float | None = None  # 年化波动率
    ret_1m: float | None = None      # 近1月收益率
    ret_3m: float | None = None      # 近3月收益率


@dataclass
class StockAnalysis:
    """股票分析结果"""
    code: str
    name: str
    shares: int
    cost_price: float | None     # None 表示未知成本
    current_price: float
    cost_value: float
    current_value: float
    profit: float
    profit_pct: float
    price_change_pct: float
    pb: float | None
    industry: str | None
    rsi: float | None
    score: int
    recommendation: str
    reason: str = ""
    volatility: float | None = None
    ret_1m: float | None = None
    ret_3m: float | None = None


@dataclass
class DepositAnalysis:
    """存款分析结果"""
    name: str
    amount: float
    annual_rate: float
    maturity: str
    interest_earned: float         # 已获利息
    interest_to_maturity: float    # 到期总利息
    total_at_maturity: float       # 到期本息合计


@dataclass
class WealthAnalysis:
    """理财分析结果"""
    name: str
    amount: float
    annual_rate: float
    buy_date: str
    maturity: str
    days_held: int
    interest_earned: float
    interest_to_maturity: float
    total_at_maturity: float


@dataclass
class PortfolioAdvice:
    """组合级投资建议"""
    summary: str                   # 总体评价
    actions: list[str]             # 具体操作建议
    risk_warnings: list[str]       # 风险提示


@dataclass
class PortfolioOverview:
    """组合概览"""
    date: str
    total_value: float
    total_cost: float
    total_profit: float
    total_profit_pct: float
    fund_value: float
    stock_value: float
    deposit_value: float
    wealth_value: float
    fund_pct: float
    stock_pct: float
    deposit_pct: float
    wealth_pct: float
    diversification_score: float   # 分散度 0~1


@dataclass
class AnalysisResult:
    """完整分析结果"""
    overview: PortfolioOverview
    funds: list[FundAnalysis]
    stocks: list[StockAnalysis]
    deposits: list[DepositAnalysis]
    wealth_products: list[WealthAnalysis]
    portfolio_advice: PortfolioAdvice


def analyze_portfolio(
    snapshot: PositionSnapshot,
    fund_data: list[FundMarketData],
    stock_data: list[StockMarketData],
    risk_free_rate: float = 0.015,
) -> AnalysisResult:
    """运行完整组合分析"""
    fund_analyses = _analyze_funds(snapshot.funds, fund_data, risk_free_rate)
    stock_analyses = _analyze_stocks(snapshot.stocks, stock_data)
    deposit_analyses = _analyze_deposits(snapshot.deposits)
    wealth_analyses = _analyze_wealth(snapshot.wealth_products)

    overview = _build_overview(
        snapshot.date, fund_analyses, stock_analyses,
        deposit_analyses, wealth_analyses,
    )

    # 计算建议评分（需要组合信息做集中度检查）
    advice = _score_recommendations(fund_analyses, stock_analyses, overview)

    return AnalysisResult(
        overview=overview,
        funds=fund_analyses,
        stocks=stock_analyses,
        deposits=deposit_analyses,
        wealth_products=wealth_analyses,
        portfolio_advice=advice,
    )


def _analyze_funds(
    positions: list[FundPosition],
    market_data: list[FundMarketData],
    risk_free_rate: float,
) -> list[FundAnalysis]:
    data_map = {d.code: d for d in market_data}
    results = []

    for pos in positions:
        md = data_map.get(pos.code)
        if not md:
            continue

        has_cost = pos.cost_nav is not None and pos.cost_nav > 0
        cost_value = pos.shares * pos.cost_nav if has_cost else 0.0
        current_value = pos.shares * md.current_nav
        profit = current_value - cost_value if has_cost else 0.0
        profit_pct = profit / cost_value if has_cost and cost_value else 0.0

        # 夏普比率
        sharpe = _calc_sharpe(md.nav_history, risk_free_rate) if not md.nav_history.empty else None

        # 最大回撤
        drawdown = _calc_max_drawdown(md.nav_history) if not md.nav_history.empty else None

        # 波动率和近期收益
        volatility = ret_1m = ret_3m = None
        if not md.nav_history.empty:
            ret_col = [c for c in md.nav_history.columns if "日增长率" in c]
            if ret_col:
                daily_ret = md.nav_history[ret_col[0]].dropna().astype(float)
                if len(daily_ret) >= 20:
                    volatility = round(float(daily_ret.std() * (252 ** 0.5)), 2)
            nav_col = [c for c in md.nav_history.columns if "单位净值" in c]
            if nav_col:
                nav = md.nav_history[nav_col[0]].astype(float)
                if len(nav) >= 20:
                    ret_1m = round(float(nav.iloc[-1] / nav.iloc[-20] - 1), 4)
                if len(nav) >= 60:
                    ret_3m = round(float(nav.iloc[-1] / nav.iloc[-60] - 1), 4)

        results.append(FundAnalysis(
            code=pos.code,
            name=pos.name,
            shares=pos.shares,
            cost_nav=pos.cost_nav,
            current_nav=md.current_nav,
            cost_value=cost_value,
            current_value=current_value,
            profit=profit,
            profit_pct=profit_pct,
            nav_change_pct=md.nav_change_pct,
            rank_pct=md.rank_pct,
            sharpe_ratio=sharpe,
            max_drawdown=drawdown,
            score=0,
            recommendation="持有",
            volatility=volatility,
            ret_1m=ret_1m,
            ret_3m=ret_3m,
        ))

    return results


def _analyze_stocks(
    positions: list[StockPosition],
    market_data: list[StockMarketData],
) -> list[StockAnalysis]:
    data_map = {d.code: d for d in market_data}
    results = []

    for pos in positions:
        md = data_map.get(pos.code)
        if not md:
            continue

        has_cost = pos.cost_price is not None and pos.cost_price > 0
        cost_value = pos.shares * pos.cost_price if has_cost else 0.0
        current_value = pos.shares * md.current_price
        profit = current_value - cost_value if has_cost else 0.0
        profit_pct = profit / cost_value if has_cost and cost_value else 0.0

        # RSI(14)
        rsi = _calc_rsi(md.price_history, period=14) if not md.price_history.empty else None

        # 波动率和近期收益
        volatility = ret_1m = ret_3m = None
        if not md.price_history.empty:
            chg_col = [c for c in md.price_history.columns if "涨跌幅" in c]
            if chg_col:
                daily_chg = md.price_history[chg_col[0]].dropna().astype(float)
                if len(daily_chg) >= 20:
                    volatility = round(float(daily_chg.std() * (252 ** 0.5)), 2)
            close_col = [c for c in md.price_history.columns if "收盘" in c]
            if close_col:
                close = md.price_history[close_col[0]].astype(float)
                if len(close) >= 20:
                    ret_1m = round(float(close.iloc[-1] / close.iloc[-20] - 1), 4)
                if len(close) >= 60:
                    ret_3m = round(float(close.iloc[-1] / close.iloc[-60] - 1), 4)

        results.append(StockAnalysis(
            code=pos.code,
            name=pos.name,
            shares=pos.shares,
            cost_price=pos.cost_price,
            current_price=md.current_price,
            cost_value=cost_value,
            current_value=current_value,
            profit=profit,
            profit_pct=profit_pct,
            price_change_pct=md.price_change_pct,
            pb=md.pb,
            industry=md.industry,
            rsi=rsi,
            score=0,
            recommendation="持有",
            volatility=volatility,
            ret_1m=ret_1m,
            ret_3m=ret_3m,
        ))

    return results


def _analyze_deposits(positions: list[DepositPosition]) -> list[DepositAnalysis]:
    results = []
    today = datetime.now()
    for pos in positions:
        try:
            maturity_dt = datetime.strptime(pos.maturity, "%Y-%m-%d")
            days_to_maturity = max(0, (maturity_dt - today).days)
            interest_to_maturity = pos.amount * pos.annual_rate * days_to_maturity / 365
            # 假设存了半年（简化计算）
            days_estimated = 180
            interest_earned = pos.amount * pos.annual_rate * days_estimated / 365
        except (ValueError, TypeError):
            interest_to_maturity = 0.0
            interest_earned = 0.0

        results.append(DepositAnalysis(
            name=pos.name,
            amount=pos.amount,
            annual_rate=pos.annual_rate,
            maturity=pos.maturity,
            interest_earned=interest_earned,
            interest_to_maturity=interest_to_maturity,
            total_at_maturity=pos.amount + interest_to_maturity,
        ))

    return results


def _analyze_wealth(positions: list[WealthPosition]) -> list[WealthAnalysis]:
    results = []
    today = datetime.now()
    for pos in positions:
        try:
            buy_dt = datetime.strptime(pos.buy_date, "%Y-%m-%d")
            maturity_dt = datetime.strptime(pos.maturity, "%Y-%m-%d")
            days_held = max(0, (today - buy_dt).days)
            days_total = max(1, (maturity_dt - buy_dt).days)
            days_remaining = max(0, (maturity_dt - today).days)

            interest_earned = pos.amount * pos.annual_rate * days_held / 365
            interest_to_maturity = pos.amount * pos.annual_rate * days_total / 365
        except (ValueError, TypeError):
            days_held = 0
            interest_earned = 0.0
            interest_to_maturity = 0.0

        results.append(WealthAnalysis(
            name=pos.name,
            amount=pos.amount,
            annual_rate=pos.annual_rate,
            buy_date=pos.buy_date,
            maturity=pos.maturity,
            days_held=days_held,
            interest_earned=interest_earned,
            interest_to_maturity=interest_to_maturity,
            total_at_maturity=pos.amount + interest_to_maturity,
        ))

    return results


def _build_overview(
    date: str,
    funds: list[FundAnalysis],
    stocks: list[StockAnalysis],
    deposits: list[DepositAnalysis],
    wealth: list[WealthAnalysis],
) -> PortfolioOverview:
    fund_value = sum(f.current_value for f in funds)
    fund_cost = sum(f.cost_value for f in funds)
    stock_value = sum(s.current_value for s in stocks)
    stock_cost = sum(s.cost_value for s in stocks)
    deposit_value = sum(d.amount for d in deposits)
    wealth_value = sum(w.amount for w in wealth)

    total_value = fund_value + stock_value + deposit_value + wealth_value
    total_cost = fund_cost + stock_cost + deposit_value + wealth_value
    total_profit = total_value - total_cost
    total_profit_pct = total_profit / total_cost if total_cost else 0.0

    fund_pct = fund_value / total_value if total_value else 0
    stock_pct = stock_value / total_value if total_value else 0
    deposit_pct = deposit_value / total_value if total_value else 0
    wealth_pct = wealth_value / total_value if total_value else 0

    # HHI 分散度
    weights = [fund_pct, stock_pct, deposit_pct, wealth_pct]
    hhi = sum(w ** 2 for w in weights if w > 0)
    diversification = 1 - hhi  # 越接近 1 越分散

    return PortfolioOverview(
        date=date,
        total_value=total_value,
        total_cost=total_cost,
        total_profit=total_profit,
        total_profit_pct=total_profit_pct,
        fund_value=fund_value,
        stock_value=stock_value,
        deposit_value=deposit_value,
        wealth_value=wealth_value,
        fund_pct=fund_pct,
        stock_pct=stock_pct,
        deposit_pct=deposit_pct,
        wealth_pct=wealth_pct,
        diversification_score=diversification,
    )


def _score_recommendations(
    funds: list[FundAnalysis],
    stocks: list[StockAnalysis],
    overview: PortfolioOverview,
) -> PortfolioAdvice:
    """为每只基金/股票计算建议评分，返回组合级建议"""
    actions: list[str] = []
    risk_warnings: list[str] = []

    for f in funds:
        reasons: list[str] = []
        score = 0

        # 1. 同类排名（权重最高）
        if f.rank_pct <= 25:
            score += 2
            reasons.append(f"同类排名前{f.rank_pct:.0f}%，表现优秀")
        elif f.rank_pct <= 50:
            score += 1
            reasons.append(f"同类排名前{f.rank_pct:.0f}%，表现中上")
        elif f.rank_pct > 75:
            score -= 2
            reasons.append(f"同类排名后{(100-f.rank_pct):.0f}%，持续跑输同类")

        # 2. 盈亏状态
        if f.profit_pct > 0.3:
            reasons.append(f"持仓盈利{f.profit_pct*100:.1f}%，可考虑部分止盈")
        elif f.profit_pct > 0.1:
            score += 1
        elif f.profit_pct < -0.2:
            score -= 1
            reasons.append(f"持仓亏损{abs(f.profit_pct)*100:.1f}%，需评估是否止损")

        # 3. 夏普比率（风险调整收益）
        if f.sharpe_ratio is not None:
            if f.sharpe_ratio > 1.5:
                score += 1
                reasons.append(f"夏普比率{f.sharpe_ratio}，承担单位风险回报高")
            elif f.sharpe_ratio < 0:
                score -= 1
                reasons.append(f"夏普比率{f.sharpe_ratio}，风险调整后收益为负")
            elif f.sharpe_ratio > 1.0:
                score += 1

        # 4. 最大回撤（风险控制能力）
        if f.max_drawdown is not None:
            if f.max_drawdown < -30:
                score -= 1
                reasons.append(f"最大回撤{abs(f.max_drawdown)}%，基金经理风控能力存疑")
            elif f.max_drawdown < -20:
                reasons.append(f"最大回撤{abs(f.max_drawdown)}%，波动偏大")

        # 5. 近期趋势
        if f.ret_3m is not None:
            if f.ret_3m < -0.15:
                score -= 1
                reasons.append(f"近3月下跌{abs(f.ret_3m)*100:.1f}%，短期趋势疲弱")
            elif f.ret_3m > 0.15:
                reasons.append(f"近3月上涨{f.ret_3m*100:.1f}%，注意追高风险")

        # 6. 波动率警告
        if f.volatility is not None and f.volatility > 25:
            reasons.append(f"年化波动率{f.volatility}%，波动较大")

        # 7. 集中度惩罚
        if overview.total_value > 0:
            weight = f.current_value / overview.total_value
            if weight > 0.30:
                score -= 1
                risk_warnings.append(f"{f.name} 占组合{weight:.0%}，单一标的集中度风险高")

        # 汇总建议
        if score >= 3:
            f.recommendation = "买入"
        elif score <= -2:
            f.recommendation = "卖出"
        else:
            f.recommendation = "持有"

        f.score = score
        f.reason = "；".join(reasons) if reasons else "各项指标中性，建议持有观察"

        if f.recommendation == "卖出":
            actions.append(f"卖出 {f.name}（{f.code}）：{f.reason}")
        elif f.recommendation == "买入" and f.rank_pct <= 25:
            actions.append(f"可加仓 {f.name}（{f.code}）：{f.reason}")

    for s in stocks:
        reasons = []
        score = 0

        # 1. RSI 技术指标
        if s.rsi is not None:
            if s.rsi < 30:
                score += 2
                reasons.append(f"RSI={s.rsi}处于超卖区间，可能存在反弹机会")
            elif s.rsi < 40:
                score += 1
                reasons.append(f"RSI={s.rsi}偏低，接近超卖")
            elif s.rsi > 70:
                score -= 2
                reasons.append(f"RSI={s.rsi}处于超买区间，回调风险较大")
            elif s.rsi > 60:
                score -= 1
                reasons.append(f"RSI={s.rsi}偏高，注意短期压力")

        # 2. 盈亏状态
        if s.profit_pct > 0.3:
            score += 1
            reasons.append(f"持仓盈利{s.profit_pct*100:.1f}%，可考虑部分止盈")
        elif s.profit_pct < -0.2:
            score -= 1
            reasons.append(f"持仓亏损{abs(s.profit_pct)*100:.1f}%")

        # 3. PB 估值
        if s.pb is not None:
            if s.pb < 1.0:
                score += 1
                reasons.append(f"PB={s.pb:.2f}破净，估值较低")
            elif s.pb > 10:
                score -= 1
                reasons.append(f"PB={s.pb:.2f}估值偏高")

        # 4. 近期趋势
        if s.ret_3m is not None:
            if s.ret_3m < -0.15:
                score -= 1
                reasons.append(f"近3月下跌{abs(s.ret_3m)*100:.1f}%，趋势偏弱")
            elif s.ret_3m > 0.2:
                reasons.append(f"近3月上涨{s.ret_3m*100:.1f}%，短期涨幅较大")

        # 5. 波动率
        if s.volatility is not None and s.volatility > 35:
            reasons.append(f"年化波动率{s.volatility}%，风险较高")

        # 6. 集中度
        if overview.total_value > 0:
            weight = s.current_value / overview.total_value
            if weight > 0.30:
                score -= 1
                risk_warnings.append(f"{s.name} 占组合{weight:.0%}，集中度风险高")

        if score >= 2:
            s.recommendation = "买入"
        elif score <= -2:
            s.recommendation = "卖出"
        else:
            s.recommendation = "持有"

        s.score = score
        s.reason = "；".join(reasons) if reasons else "各项指标中性，建议持有观察"

        if s.recommendation == "卖出":
            actions.append(f"卖出 {s.name}（{s.code}）：{s.reason}")
        elif s.recommendation == "买入":
            actions.append(f"可加仓 {s.name}（{s.code}）：{s.reason}")

    # 组合级分析
    if overview.deposit_pct + overview.wealth_pct < 0.1:
        actions.append("低风险资产（存款+理财）不足10%，建议适当增加以应对突发资金需求")

    if overview.fund_pct > 0.8:
        risk_warnings.append(f"基金占比{overview.fund_pct:.0%}过高，单一资产类型风险集中")

    if overview.stock_pct > 0.4:
        risk_warnings.append(f"股票占比{overview.stock_pct:.0%}，需关注市场波动对组合的冲击")

    # 总评
    sell_count = sum(1 for f in funds if f.recommendation == "卖出") + \
                 sum(1 for s in stocks if s.recommendation == "卖出")
    buy_count = sum(1 for f in funds if f.recommendation == "买入") + \
                sum(1 for s in stocks if f.recommendation == "买入")

    if sell_count >= 2:
        summary = f"有 {sell_count} 只标的建议卖出，组合质量需要关注，建议优先处理表现最差的标的。"
    elif buy_count >= 2 and sell_count == 0:
        summary = f"有 {buy_count} 只标的建议买入/加仓，当前持仓整体健康，可在市场回调时择机加仓。"
    elif not actions:
        summary = "当前持仓整体健康，无需大幅调整。建议每月复查，关注基金排名变化和股票技术指标。"
    else:
        summary = "持仓基本合理，有少量调整建议，详见下方具体操作。"

    return PortfolioAdvice(
        summary=summary,
        actions=actions,
        risk_warnings=risk_warnings,
    )


def _calc_sharpe(nav_df: pd.DataFrame, risk_free_rate: float) -> float | None:
    """计算夏普比率（基于日增长率）"""
    col = [c for c in nav_df.columns if "日增长率" in c]
    if not col:
        return None
    returns = nav_df[col[0]].dropna().astype(float)
    if len(returns) < 30:
        return None
    # 日收益率转年化
    daily_rf = risk_free_rate / 252
    excess = returns / 100 - daily_rf
    sharpe = (excess.mean() / excess.std()) * (252 ** 0.5) if excess.std() > 0 else 0.0
    return round(float(sharpe), 2)


def _calc_max_drawdown(nav_df: pd.DataFrame) -> float | None:
    """计算最大回撤"""
    col = [c for c in nav_df.columns if "单位净值" in c]
    if not col:
        return None
    nav = nav_df[col[0]].astype(float)
    if len(nav) < 10:
        return None
    peak = nav.cummax()
    drawdown = (nav - peak) / peak
    return round(float(drawdown.min()) * 100, 2)  # 百分比


def _calc_rsi(price_df: pd.DataFrame, period: int = 14) -> float | None:
    """计算 RSI 指标"""
    col = [c for c in price_df.columns if "收盘" in c]
    if not col:
        return None
    close = price_df[col[0]].astype(float)
    if len(close) < period + 1:
        return None
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss.replace(0, float("inf"))
    rsi = 100 - (100 / (1 + rs))
    return round(float(rsi.iloc[-1]), 2)
