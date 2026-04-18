"""报告生成器 - 同时输出 Markdown（Obsidian）+ HTML（浏览器）"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import plotly.graph_objects as go
from jinja2 import Environment, FileSystemLoader

from pa.analyzer import (
    AnalysisResult, DepositAnalysis, FundAnalysis,
    PortfolioAdvice, PortfolioOverview, StockAnalysis, WealthAnalysis,
)
from pa.fetcher import FundMarketData, StockMarketData
from pa.portfolio_theory import AllocationAdvice


def _fmt_money(v: float) -> str:
    if v >= 10000:
        return f"{v/10000:,.2f}万"
    return f"{v:,.2f}"


def _fmt_pct(v: float) -> str:
    return f"{v*100:+.2f}%"


def _fmt_pct_rank(v: float) -> str:
    return f"{v:.1f}%"


def _rec_emoji(rec: str) -> str:
    return {"买入": "🟢", "持有": "🟡", "卖出": "🔴"}.get(rec, "⚪")


def generate_report(
    result: AnalysisResult,
    fund_data: list[FundMarketData] | None = None,
    stock_data: list[StockMarketData] | None = None,
    output_dir: str = "output",
) -> list[str]:
    """同时生成 Markdown 和 HTML 报告，返回输出文件路径列表"""
    md_path = _generate_markdown(result, output_dir)
    html_path = _generate_html(result, fund_data or [], stock_data or [], output_dir)
    return [md_path, html_path]


# ── 公共格式化 ──────────────────────────────────────────────

def _fmt_allocation_advice(advice: AllocationAdvice | None) -> dict | None:
    """格式化资产配置建议数据，供模板使用"""
    if advice is None:
        return None

    cls_names = {"equity": "权益类", "fixed_income": "固收类", "cash_like": "现金类", "alternative": "另类"}
    saa_rows = []
    for key, label in cls_names.items():
        target = getattr(advice.saa_target, f"{key}_pct", 0)
        current = getattr(advice.saa_current, f"{key}_pct", 0)
        dev = getattr(advice.saa_deviation, f"{key}_pct", 0)
        saa_rows.append({
            "cls": label,
            "target": f"{target:.0%}",
            "current": f"{current:.0%}",
            "deviation": f"{dev:+.0%}",
            "dev_positive": dev >= 0,
        })

    # 相关性警告
    corr_warnings = []
    if advice.correlation and advice.correlation.high_corr_pairs:
        for a_name, b_name, corr_val in advice.correlation.high_corr_pairs:
            corr_warnings.append(f"{a_name} vs {b_name}: 相关系数 {corr_val:.2f}")

    # 风险贡献
    risk_rows = []
    if advice.risk_budget and advice.risk_budget.asset_risk_contribution:
        for name, rc in sorted(
            advice.risk_budget.asset_risk_contribution.items(),
            key=lambda x: x[1], reverse=True
        ):
            risk_rows.append({
                "name": name,
                "rc_pct": f"{rc:.1%}",
                "bar_width": max(int(rc * 100), 2),
            })

    # 基准对比
    benchmark_rows = []
    for b in advice.benchmarks:
        benchmark_rows.append({
            "name": b.benchmark_name,
            "portfolio_return": f"{b.portfolio_return:.2%}",
            "benchmark_return": f"{b.benchmark_return:.2%}",
            "alpha": f"{b.alpha:+.2%}",
            "alpha_positive": b.alpha >= 0,
        })

    # 情景分析
    scenario_rows = []
    for s in advice.scenarios:
        scenario_rows.append({
            "name": s.scenario_name,
            "return_str": f"{s.estimated_return:+.2%}",
            "drawdown_str": f"{s.estimated_drawdown:.2%}",
            "description": s.description,
        })

    # 全天候评分等级
    score = advice.all_weather_score
    if score >= 80:
        score_level = "优秀"
        score_color = "#27ae60"
    elif score >= 60:
        score_level = "良好"
        score_color = "#2ecc71"
    elif score >= 40:
        score_level = "一般"
        score_color = "#f39c12"
    elif score >= 20:
        score_level = "较差"
        score_color = "#e67e22"
    else:
        score_level = "危险"
        score_color = "#e74c3c"

    return {
        "saa_rows": saa_rows,
        "all_weather_score": f"{score:.0f}",
        "all_weather_level": score_level,
        "all_weather_color": score_color,
        "corr_warnings": corr_warnings,
        "risk_rows": risk_rows,
        "benchmark_rows": benchmark_rows,
        "scenario_rows": scenario_rows,
        "rebalance_actions": advice.rebalance_actions,
        "value_signals": advice.value_signals,
        "cost_warnings": advice.cost_warnings,
        "theory_summary": advice.theory_summary,
    }


def _fmt_deposit(d: DepositAnalysis) -> dict:
    return {
        "name": d.name,
        "amount_str": _fmt_money(d.amount),
        "rate_str": f"{d.annual_rate*100:.2f}%",
        "maturity": d.maturity,
        "total_str": _fmt_money(d.total_at_maturity),
    }


def _fmt_wealth(w: WealthAnalysis) -> dict:
    return {
        "name": w.name,
        "amount_str": _fmt_money(w.amount),
        "rate_str": f"{w.annual_rate*100:.2f}%",
        "buy_date": w.buy_date,
        "maturity": w.maturity,
        "days_held": w.days_held,
        "total_str": _fmt_money(w.total_at_maturity),
    }


# ── Markdown 报告（Obsidian）─────────────────────────────────

def _generate_markdown(result: AnalysisResult, output_dir: str) -> str:
    o = result.overview
    advice = result.portfolio_advice

    allocation_mermaid = []
    if o.fund_value > 0:
        allocation_mermaid.append({"label": "基金", "value": round(o.fund_value)})
    if o.stock_value > 0:
        allocation_mermaid.append({"label": "股票", "value": round(o.stock_value)})
    if o.deposit_value > 0:
        allocation_mermaid.append({"label": "存款", "value": round(o.deposit_value)})
    if o.wealth_value > 0:
        allocation_mermaid.append({"label": "理财", "value": round(o.wealth_value)})

    template_data = {
        "date": o.date,
        "gen_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total_value": _fmt_money(o.total_value),
        "total_profit": _fmt_money(abs(o.total_profit)),
        "total_profit_pct": _fmt_pct(o.total_profit_pct),
        "diversification_score": f"{o.diversification_score:.0%}",
        "diversification_hint": "分散良好" if o.diversification_score > 0.6 else "较为集中",
        "asset_count": len(result.funds) + len(result.stocks) + len(result.deposits) + len(result.wealth_products),
        "asset_detail": f"{len(result.funds)}基金 {len(result.stocks)}股票 {len(result.deposits)}存款 {len(result.wealth_products)}理财",
        "advice_summary": advice.summary,
        "advice_actions": advice.actions,
        "risk_warnings": advice.risk_warnings,
        "allocation_mermaid": allocation_mermaid,
        "allocation_advice": _fmt_allocation_advice(result.allocation_advice),
        "funds": [_fmt_fund_md(f) for f in result.funds],
        "stocks": [_fmt_stock_md(s) for s in result.stocks],
        "deposits": [_fmt_deposit(d) for d in result.deposits],
        "wealth": [_fmt_wealth(w) for w in result.wealth_products],
    }

    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=False,
    )
    md = env.get_template("report.md").render(**template_data)

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    filename = f"report_{o.date.replace('-', '')}.md"
    filepath = out_path / filename
    filepath.write_text(md, encoding="utf-8")
    return str(filepath)


def _fmt_fund_md(f: FundAnalysis) -> dict:
    return {
        "code": f.code,
        "name": f.name,
        "profit_str": _fmt_money(abs(f.profit)),
        "profit_pct_str": _fmt_pct(f.profit_pct),
        "rank_pct_str": _fmt_pct_rank(f.rank_pct),
        "sharpe_str": f"{f.sharpe_ratio:.2f}" if f.sharpe_ratio is not None else "-",
        "max_drawdown_str": f"{f.max_drawdown:.2f}%" if f.max_drawdown is not None else "-",
        "recommendation": f.recommendation,
        "rec_emoji": _rec_emoji(f.recommendation),
        "reason": f.reason,
        "volatility": f"{f.volatility}%" if f.volatility else "-",
        "ret_1m": f"{f.ret_1m*100:+.2f}%" if f.ret_1m else "-",
        "ret_3m": f"{f.ret_3m*100:+.2f}%" if f.ret_3m else "-",
    }


def _fmt_stock_md(s: StockAnalysis) -> dict:
    return {
        "code": s.code,
        "name": s.name,
        "profit_str": _fmt_money(abs(s.profit)),
        "profit_pct_str": _fmt_pct(s.profit_pct),
        "rsi_str": f"{s.rsi:.1f}" if s.rsi else "-",
        "pb_str": f"{s.pb:.2f}" if s.pb else "-",
        "recommendation": s.recommendation,
        "rec_emoji": _rec_emoji(s.recommendation),
        "reason": s.reason,
        "volatility": f"{s.volatility}%" if s.volatility else "-",
        "ret_1m": f"{s.ret_1m*100:+.2f}%" if s.ret_1m else "-",
        "ret_3m": f"{s.ret_3m*100:+.2f}%" if s.ret_3m else "-",
    }


# ── HTML 报告（浏览器）──────────────────────────────────────

def _generate_html(
    result: AnalysisResult,
    fund_data: list[FundMarketData],
    stock_data: list[StockMarketData],
    output_dir: str,
) -> str:
    o = result.overview
    advice = result.portfolio_advice

    allocation_chart = _chart_allocation(o)
    pnl_chart = _chart_pnl(result)
    fund_trend_chart = _chart_fund_trend(result, fund_data)
    stock_trend_chart = _chart_stock_trend(result, stock_data)

    template_data = {
        "date": o.date,
        "gen_time": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "total_value": _fmt_money(o.total_value),
        "total_profit_raw": o.total_profit,
        "total_profit": _fmt_money(abs(o.total_profit)),
        "total_profit_pct": _fmt_pct(o.total_profit_pct),
        "diversification_score": f"{o.diversification_score:.0%}",
        "diversification_hint": "分散良好" if o.diversification_score > 0.6 else "较为集中",
        "asset_count": len(result.funds) + len(result.stocks) + len(result.deposits) + len(result.wealth_products),
        "asset_detail": f"{len(result.funds)}基金 {len(result.stocks)}股票 {len(result.deposits)}存款 {len(result.wealth_products)}理财",
        "advice_summary": advice.summary,
        "advice_actions": advice.actions,
        "risk_warnings": advice.risk_warnings,
        "allocation_chart": allocation_chart,
        "pnl_chart": pnl_chart,
        "fund_trend_chart": fund_trend_chart,
        "stock_trend_chart": stock_trend_chart,
        "saa_chart": _chart_saa(result.allocation_advice),
        "risk_chart": _chart_risk_contribution(result.allocation_advice),
        "allocation_advice": _fmt_allocation_advice(result.allocation_advice),
        "funds": [_fmt_fund_html(f) for f in result.funds],
        "stocks": [_fmt_stock_html(s) for s in result.stocks],
        "deposits": [_fmt_deposit(d) for d in result.deposits],
        "wealth": [_fmt_wealth(w) for w in result.wealth_products],
    }

    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=True,
    )
    html = env.get_template("report.html").render(**template_data)

    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    filename = f"report_{o.date.replace('-', '')}.html"
    filepath = out_path / filename
    filepath.write_text(html, encoding="utf-8")
    return str(filepath)


def _fmt_fund_html(f: FundAnalysis) -> dict:
    return {
        "code": f.code,
        "name": f.name,
        "cost_nav": f"{f.cost_nav:.4f}" if f.cost_nav else "-",
        "current_nav": f"{f.current_nav:.4f}",
        "profit": f.profit,
        "profit_str": _fmt_money(abs(f.profit)),
        "profit_pct": f.profit_pct,
        "profit_pct_str": _fmt_pct(f.profit_pct),
        "nav_change_pct": f.nav_change_pct,
        "nav_change_pct_str": f"{f.nav_change_pct:+.2f}%",
        "rank_pct": f.rank_pct,
        "rank_pct_str": _fmt_pct_rank(f.rank_pct),
        "sharpe_ratio": f.sharpe_ratio,
        "sharpe_str": f"{f.sharpe_ratio:.2f}" if f.sharpe_ratio is not None else "-",
        "max_drawdown": f.max_drawdown,
        "max_drawdown_str": f"{f.max_drawdown:.2f}%" if f.max_drawdown is not None else "-",
        "recommendation": f.recommendation,
        "rec_class": {"买入": "buy", "持有": "hold", "卖出": "sell"}.get(f.recommendation, "hold"),
        "reason": f.reason,
        "volatility": f"{f.volatility}%" if f.volatility else "-",
        "ret_1m": f"{f.ret_1m*100:+.2f}%" if f.ret_1m else "-",
        "ret_3m": f"{f.ret_3m*100:+.2f}%" if f.ret_3m else "-",
    }


def _fmt_stock_html(s: StockAnalysis) -> dict:
    return {
        "code": s.code,
        "name": s.name,
        "cost_price": f"{s.cost_price:.2f}" if s.cost_price else "-",
        "current_price": f"{s.current_price:.2f}",
        "profit": s.profit,
        "profit_str": _fmt_money(abs(s.profit)),
        "profit_pct": s.profit_pct,
        "profit_pct_str": _fmt_pct(s.profit_pct),
        "price_change_pct": s.price_change_pct,
        "price_change_pct_str": f"{s.price_change_pct:+.2f}%",
        "pb": s.pb,
        "pb_str": f"{s.pb:.2f}" if s.pb else "-",
        "rsi": s.rsi,
        "rsi_str": f"{s.rsi:.1f}" if s.rsi else "-",
        "recommendation": s.recommendation,
        "rec_class": {"买入": "buy", "持有": "hold", "卖出": "sell"}.get(s.recommendation, "hold"),
        "reason": s.reason,
        "volatility": f"{s.volatility}%" if s.volatility else "-",
        "ret_1m": f"{s.ret_1m*100:+.2f}%" if s.ret_1m else "-",
        "ret_3m": f"{s.ret_3m*100:+.2f}%" if s.ret_3m else "-",
    }


# ── Plotly 图表 ─────────────────────────────────────────────

def _chart_allocation(o: PortfolioOverview) -> str:
    labels, values, colors = [], [], []
    if o.fund_value > 0:
        labels.append("基金"); values.append(o.fund_value); colors.append("#3498db")
    if o.stock_value > 0:
        labels.append("股票"); values.append(o.stock_value); colors.append("#e74c3c")
    if o.deposit_value > 0:
        labels.append("存款"); values.append(o.deposit_value); colors.append("#2ecc71")
    if o.wealth_value > 0:
        labels.append("理财"); values.append(o.wealth_value); colors.append("#f39c12")

    fig = go.Figure(data=[go.Pie(
        labels=labels, values=values,
        marker_colors=colors, hole=0.45,
        textinfo="label+percent", textposition="outside",
    )])
    fig.update_layout(margin=dict(t=0, b=0, l=0, r=0), height=300, showlegend=False)
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _chart_pnl(result: AnalysisResult) -> str:
    names, profits, colors = [], [], []
    for f in result.funds:
        names.append(f.name[:6]); profits.append(f.profit)
        colors.append("#e74c3c" if f.profit >= 0 else "#2ecc71")
    for s in result.stocks:
        names.append(s.name[:6]); profits.append(s.profit)
        colors.append("#e74c3c" if s.profit >= 0 else "#2ecc71")

    fig = go.Figure(data=[go.Bar(
        x=names, y=profits, marker_color=colors,
        text=[_fmt_money(p) if p >= 0 else f"-{_fmt_money(abs(p))}" for p in profits],
        textposition="outside",
    )])
    fig.update_layout(margin=dict(t=0, b=40, l=50, r=0), height=300, yaxis_title="盈亏金额")
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _chart_fund_trend(result: AnalysisResult, fund_data: list[FundMarketData]) -> str:
    fig = go.Figure()
    data_map = {d.code: d for d in fund_data}
    for f in result.funds:
        md = data_map.get(f.code)
        if not md or md.nav_history.empty:
            continue
        df = md.nav_history.tail(120)
        date_col = df.columns[0]
        nav_col = [c for c in df.columns if "单位净值" in c][0]
        fig.add_trace(go.Scatter(x=df[date_col], y=df[nav_col], name=f.name[:8], mode="lines"))

    if fig.data:
        fig.update_layout(margin=dict(t=10, b=40, l=60, r=0), height=350,
                          xaxis_title="日期", yaxis_title="净值", legend=dict(orientation="h", y=-0.15))
    else:
        fig.update_layout(margin=dict(t=0, b=0, l=0, r=0), height=200)
        fig.add_annotation(text="暂无历史数据", showarrow=False)
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _chart_stock_trend(result: AnalysisResult, stock_data: list[StockMarketData]) -> str:
    fig = go.Figure()
    data_map = {d.code: d for d in stock_data}
    for s in result.stocks:
        md = data_map.get(s.code)
        if not md or md.price_history.empty:
            continue
        df = md.price_history.tail(60)
        date_col = [c for c in df.columns if "日期" in c][0]
        close_col = [c for c in df.columns if "收盘" in c][0]
        fig.add_trace(go.Scatter(x=df[date_col], y=df[close_col], name=s.name[:6], mode="lines"))

    if fig.data:
        fig.update_layout(margin=dict(t=10, b=40, l=60, r=0), height=350,
                          xaxis_title="日期", yaxis_title="价格", legend=dict(orientation="h", y=-0.15))
    else:
        fig.update_layout(margin=dict(t=0, b=0, l=0, r=0), height=200)
        fig.add_annotation(text="暂无历史数据", showarrow=False)
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _chart_saa(advice) -> str:
    """SAA 目标 vs 实际配置对比柱状图"""
    fig = go.Figure()
    cls_names = {"equity": "权益类", "fixed_income": "固收类", "cash_like": "现金类", "alternative": "另类"}
    if not advice:
        fig.update_layout(margin=dict(t=0, b=0, l=0, r=0), height=200)
        fig.add_annotation(text="暂无配置数据", showarrow=False)
        return fig.to_html(full_html=False, include_plotlyjs=False)

    categories = list(cls_names.values())
    targets = [getattr(advice.saa_target, f"{k}_pct", 0) * 100 for k in cls_names]
    currents = [getattr(advice.saa_current, f"{k}_pct", 0) * 100 for k in cls_names]

    fig.add_trace(go.Bar(name="目标配置", x=categories, y=targets, marker_color="#3498db"))
    fig.add_trace(go.Bar(name="实际配置", x=categories, y=currents, marker_color="#e67e22"))
    fig.update_layout(
        barmode="group", margin=dict(t=10, b=40, l=50, r=0), height=300,
        yaxis_title="占比 (%)", legend=dict(orientation="h", y=-0.15),
    )
    return fig.to_html(full_html=False, include_plotlyjs=False)


def _chart_risk_contribution(advice) -> str:
    """风险贡献分布图"""
    fig = go.Figure()
    if not advice or not advice.risk_budget or not advice.risk_budget.asset_risk_contribution:
        fig.update_layout(margin=dict(t=0, b=0, l=0, r=0), height=200)
        fig.add_annotation(text="暂无风险数据", showarrow=False)
        return fig.to_html(full_html=False, include_plotlyjs=False)

    rc = advice.risk_budget.asset_risk_contribution
    names = [n[:8] for n in rc]
    values = [v * 100 for v in rc.values()]
    colors = ["#e74c3c" if v > 15 else "#f39c12" if v > 10 else "#3498db" for v in values]

    fig.add_trace(go.Bar(x=names, y=values, marker_color=colors))
    fig.update_layout(
        margin=dict(t=10, b=60, l=50, r=0), height=300,
        yaxis_title="风险贡献 (%)",
        xaxis=dict(tickangle=30),
    )
    return fig.to_html(full_html=False, include_plotlyjs=False)
