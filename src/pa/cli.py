"""CLI 入口 - Click 命令行工具"""

from __future__ import annotations

import webbrowser
from pathlib import Path

import click
import yaml

from pa import __version__


def _load_config(config_path: str) -> dict:
    """加载配置"""
    path = Path(config_path)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}


@click.group()
@click.version_option(__version__, prog_name="pa")
@click.option("--config", default="config.yaml", help="配置文件路径")
@click.pass_context
def cli(ctx: click.Context, config: str) -> None:
    """个人持仓分析工具 (Position Analysis)"""
    ctx.ensure_object(dict)
    ctx.obj["config"] = _load_config(config)


@cli.command()
@click.option("--data-dir", default=None, help="持仓数据目录（覆盖配置）")
@click.option("--output-dir", default=None, help="报告输出目录（覆盖配置）")
@click.option("--no-open", is_flag=True, help="不自动打开浏览器")
@click.pass_context
def analyze(ctx: click.Context, data_dir: str | None, output_dir: str | None,
            no_open: bool) -> None:
    """运行完整分析并生成 HTML 报告"""
    cfg = ctx.obj["config"]
    data_dir = data_dir or cfg.get("data_dir", "./data")
    output_dir = output_dir or cfg.get("output_dir", "./output")
    cache_dir = cfg.get("cache_dir", ".cache")
    cache_max_age = cfg.get("cache_max_age_hours", 4)
    risk_free_rate = cfg.get("risk_free_rate", 0.015)

    from pa.parser import parse_all_files
    from pa.fetcher import fetch_all_data
    from pa.analyzer import analyze_portfolio
    from pa.report import generate_report

    # 1. 解析最新持仓文件
    click.echo("解析持仓数据...")
    snapshots = parse_all_files(data_dir)
    if not snapshots:
        click.echo(f"错误: 在 {data_dir} 中未找到持仓文件")
        raise SystemExit(1)

    snapshot = snapshots[-1]  # 最新快照
    click.echo(f"  数据日期: {snapshot.date}")
    click.echo(f"  基金 {len(snapshot.funds)} 只 | 股票 {len(snapshot.stocks)} 只 | "
               f"存款 {len(snapshot.deposits)} 笔 | 理财 {len(snapshot.wealth_products)} 笔")

    if not snapshot.funds and not snapshot.stocks:
        click.echo("错误: 持仓文件中没有基金或股票数据")
        raise SystemExit(1)

    # 2. 获取市场数据
    click.echo("\n获取实时行情数据...")
    fund_data, stock_data, benchmark_data = fetch_all_data(snapshot, cache_dir, cache_max_age)

    # 3. 运行分析
    click.echo("\n分析中...")
    result = analyze_portfolio(snapshot, fund_data, stock_data, risk_free_rate,
                               config=cfg, benchmark_data=benchmark_data)

    o = result.overview
    click.echo(f"  总资产: {o.total_value:,.2f}")
    click.echo(f"  总盈亏: {o.total_profit:,.2f} ({o.total_profit_pct*100:+.2f}%)")

    # 4. 生成报告
    click.echo("\n生成报告...")
    filepaths = generate_report(result, fund_data, stock_data, output_dir)
    for fp in filepaths:
        click.echo(f"  报告已生成: {fp}")

    # 5. 打开浏览器（优先打开 HTML 版本）
    if not no_open:
        html_path = next((p for p in filepaths if p.endswith(".html")), None)
        if html_path:
            click.echo("  正在打开浏览器...")
            webbrowser.open(f"file:///{Path(html_path).resolve()}")


@cli.command()
@click.option("--data-dir", default=None, help="持仓数据目录")
@click.pass_context
def fetch(ctx: click.Context, data_dir: str | None) -> None:
    """仅获取最新行情数据并缓存"""
    cfg = ctx.obj["config"]
    data_dir = data_dir or cfg.get("data_dir", "./data")
    cache_dir = cfg.get("cache_dir", ".cache")
    cache_max_age = cfg.get("cache_max_age_hours", 4)

    from pa.parser import parse_all_files
    from pa.fetcher import fetch_all_data

    snapshots = parse_all_files(data_dir)
    if not snapshots:
        click.echo(f"错误: 在 {data_dir} 中未找到持仓文件")
        raise SystemExit(1)

    snapshot = snapshots[-1]
    click.echo(f"获取 {snapshot.date} 的行情数据...")
    fetch_all_data(snapshot, cache_dir, cache_max_age)  # noqa: F841 (benchmark also fetched)
    click.echo("完成。数据已缓存。")


@cli.command()
@click.option("--data-dir", default=None, help="持仓数据目录")
@click.pass_context
def history(ctx: click.Context, data_dir: str | None) -> None:
    """显示历史趋势（需要多个周快照）"""
    cfg = ctx.obj["config"]
    data_dir = data_dir or cfg.get("data_dir", "./data")

    from pa.parser import parse_all_files

    snapshots = parse_all_files(data_dir)
    if len(snapshots) < 2:
        click.echo(f"需要至少 2 个快照文件，当前只有 {len(snapshots)} 个")
        raise SystemExit(1)

    click.echo(f"共 {len(snapshots)} 个快照:")
    for s in snapshots:
        fund_total = sum(f.shares * f.cost_nav for f in s.funds)
        stock_total = sum(st.shares * st.cost_price for st in s.stocks)
        deposit_total = sum(d.amount for d in s.deposits)
        wealth_total = sum(w.amount for w in s.wealth_products)
        total = fund_total + stock_total + deposit_total + wealth_total
        click.echo(f"  {s.date}: 成本 {total:,.2f} ({len(s.funds)}基金 {len(s.stocks)}股票)")

    click.echo("\n提示: 历史趋势需要结合实时行情数据，请使用 `pa analyze` 生成完整报告。")
