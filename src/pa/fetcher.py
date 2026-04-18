"""市场数据获取层 - akshare + 天天基金 API（带 Parquet 缓存）"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import akshare as ak
import pandas as pd
import yaml


@dataclass
class FundMarketData:
    """基金市场数据"""
    code: str
    name: str
    current_nav: float          # 最新净值
    nav_change_pct: float       # 日涨跌幅 %
    nav_history: pd.DataFrame   # 历史净值: [日期, 单位净值, 日增长率]
    rank_pct: float             # 同类排名百分比（越小越好）


@dataclass
class StockMarketData:
    """股票市场数据"""
    code: str
    name: str
    current_price: float        # 最新收盘价
    price_change_pct: float     # 日涨跌幅 %
    price_history: pd.DataFrame # 历史行情: [日期, 开盘, 收盘, 最高, 最低]
    pe: float | None            # 市盈率
    pb: float | None            # 市净率
    industry: str | None        # 所属行业


def load_config(config_path: str = "config.yaml") -> dict:
    """加载配置文件"""
    path = Path(config_path)
    if path.exists():
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}


def _cache_path(cache_dir: str, prefix: str, code: str, date_str: str) -> Path:
    """生成缓存文件路径"""
    dir_path = Path(cache_dir)
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path / f"{prefix}_{code}_{date_str}.parquet"


def _is_cache_valid(path: Path, max_age_hours: int) -> bool:
    """检查缓存是否有效"""
    if not path.exists():
        return False
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return datetime.now() - mtime < timedelta(hours=max_age_hours)


def _today_str() -> str:
    return datetime.now().strftime("%Y%m%d")


def _retry(func, retries=2, delay=3):
    """带重试的函数调用"""
    for attempt in range(retries + 1):
        try:
            return func()
        except Exception as e:
            if attempt == retries:
                raise
            print(f"  请求失败，{delay}s 后重试 ({attempt+1}/{retries}): {e}")
            time.sleep(delay)


def fetch_fund_data(code: str, cache_dir: str = ".cache",
                    max_age_hours: int = 4) -> FundMarketData:
    """获取单只基金的市场数据"""
    today = _today_str()
    name = ""

    # 尝试从缓存加载净值历史
    nav_cache = _cache_path(cache_dir, "fund_nav", code, today)
    if _is_cache_valid(nav_cache, max_age_hours):
        nav_history = pd.read_parquet(nav_cache)
    else:
        nav_history = _retry(lambda: ak.fund_open_fund_info_em(
            symbol=code, indicator="单位净值走势"
        ))
        nav_history.to_parquet(nav_cache)

    # 最新净值
    if not nav_history.empty:
        last_row = nav_history.iloc[-1]
        current_nav = float(last_row["单位净值"])
        nav_change_pct = float(last_row["日增长率"]) if "日增长率" in nav_history.columns else 0.0
        name = nav_history.columns[0]  # 列名里可能包含基金名
    else:
        current_nav = 0.0
        nav_change_pct = 0.0

    # 同类排名
    rank_cache = _cache_path(cache_dir, "fund_rank", code, today)
    rank_pct = 50.0  # 默认中等
    if _is_cache_valid(rank_cache, max_age_hours):
        rank_df = pd.read_parquet(rank_cache)
    else:
        try:
            rank_df = _retry(lambda: ak.fund_open_fund_info_em(
                symbol=code, indicator="同类排名百分比"
            ))
            rank_df.to_parquet(rank_cache)
        except Exception:
            rank_df = pd.DataFrame()
    if not rank_df.empty:
        last_rank = rank_df.iloc[-1]
        rank_col = [c for c in rank_df.columns if "百分比" in c]
        if rank_col:
            rank_pct = float(last_rank[rank_col[0]])

    return FundMarketData(
        code=code,
        name=name,
        current_nav=current_nav,
        nav_change_pct=nav_change_pct,
        nav_history=nav_history,
        rank_pct=rank_pct,
    )


def _is_hk_stock(code: str) -> bool:
    """判断是否为港股（H 前缀，如 H03690）"""
    return code.upper().startswith("H")


def fetch_stock_data(code: str, cache_dir: str = ".cache",
                     max_age_hours: int = 4) -> StockMarketData:
    """获取单只股票的市场数据（支持 A 股和港股）"""
    today = _today_str()

    # 历史行情（最近90天）
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=90)).strftime("%Y%m%d")

    price_cache = _cache_path(cache_dir, "stock_price", code, today)
    if _is_cache_valid(price_cache, max_age_hours):
        price_history = pd.read_parquet(price_cache)
    else:
        if _is_hk_stock(code):
            # 港股：去掉 H 前缀，用数字代码
            hk_code = code[1:]
            price_history = _retry(lambda: ak.stock_hk_hist(
                symbol=hk_code, period="daily",
                start_date=start_date, end_date=end_date, adjust="qfq"
            ))
        else:
            price_history = _retry(lambda: ak.stock_zh_a_hist(
                symbol=code, period="daily",
                start_date=start_date, end_date=end_date, adjust="qfq"
            ))
        price_history.to_parquet(price_cache)

    # 最新价格
    current_price = 0.0
    price_change_pct = 0.0
    if not price_history.empty:
        last_row = price_history.iloc[-1]
        current_price = float(last_row["收盘"])
        price_change_pct = float(last_row["涨跌幅"]) if "涨跌幅" in price_history.columns else 0.0

    # PB（PE 可选）
    pb = None
    try:
        pb_df = ak.stock_zh_valuation_baidu(symbol=code, indicator="市净率")
        if not pb_df.empty:
            pb = float(pb_df.iloc[-1]["value"])
    except Exception:
        pass

    # 行业信息
    industry = None
    try:
        info_df = ak.stock_individual_info_em(symbol=code)
        for _, row in info_df.iterrows():
            if row["item"] == "行业":
                industry = str(row["value"])
                break
    except Exception:
        pass

    # 名称从历史数据获取
    name = ""
    if not price_history.empty and "股票名称" in price_history.columns:
        name = str(price_history.iloc[-1]["股票名称"])

    return StockMarketData(
        code=code,
        name=name,
        current_price=current_price,
        price_change_pct=price_change_pct,
        price_history=price_history,
        pe=None,  # 百度数据源不稳定，PE 暂不获取
        pb=pb,
        industry=industry,
    )


def fetch_all_data(snapshot, cache_dir: str = ".cache",
                   max_age_hours: int = 4) -> tuple[list[FundMarketData], list[StockMarketData], dict]:
    """获取快照中所有基金和股票的市场数据，以及基准指数数据"""
    fund_data = []
    stock_data = []

    for fund in snapshot.funds:
        print(f"  获取基金 {fund.code} {fund.name} ...")
        try:
            fund_data.append(fetch_fund_data(fund.code, cache_dir, max_age_hours))
        except Exception as e:
            print(f"  警告: 获取基金 {fund.code} 失败: {e}")
            fund_data.append(FundMarketData(
                code=fund.code, name=fund.name,
                current_nav=fund.cost_nav or 0.0, nav_change_pct=0.0,
                nav_history=pd.DataFrame(), rank_pct=50.0,
            ))

    for stock in snapshot.stocks:
        print(f"  获取股票 {stock.code} {stock.name} ...")
        try:
            stock_data.append(fetch_stock_data(stock.code, cache_dir, max_age_hours))
        except Exception as e:
            print(f"  警告: 获取股票 {stock.code} 失败: {e}")
            stock_data.append(StockMarketData(
                code=stock.code, name=stock.name,
                current_price=stock.cost_price or 0.0, price_change_pct=0.0,
                price_history=pd.DataFrame(), pe=None, pb=None, industry=None,
            ))

    # 获取基准指数数据
    benchmark_data = {}
    try:
        from pa.benchmark_fetcher import fetch_benchmark_data
        benchmark_data = fetch_benchmark_data(cache_dir, days=120)
    except Exception as e:
        print(f"  警告: 获取基准指数数据失败: {e}")

    return fund_data, stock_data, benchmark_data
