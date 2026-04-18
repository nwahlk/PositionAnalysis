"""基准指数数据获取 — akshare 获取沪深300、中证全债等"""

from __future__ import annotations

import time
from pathlib import Path

import akshare as ak
import pandas as pd


def _cache_path(cache_dir: str, index_code: str, date_str: str) -> Path:
    dir_path = Path(cache_dir)
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path / f"index_{index_code}_{date_str}.parquet"


def _is_cache_valid(path: Path, max_age_hours: int) -> bool:
    if not path.exists():
        return False
    from datetime import datetime, timedelta
    mtime = datetime.fromtimestamp(path.stat().st_mtime)
    return datetime.now() - mtime < timedelta(hours=max_age_hours)


def _retry(func, retries=2, delay=3):
    for attempt in range(retries + 1):
        try:
            return func()
        except Exception as e:
            if attempt == retries:
                raise
            print(f"  请求失败，{delay}s 后重试 ({attempt+1}/{retries}): {e}")
            time.sleep(delay)


def fetch_index_history(
    symbol: str,
    days: int = 120,
    cache_dir: str = ".cache",
    max_age_hours: int = 24,
) -> pd.Series:
    """获取指数日 K 线，返回收盘价序列（日期索引）"""
    from datetime import datetime
    today = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - pd.Timedelta(days=days + 30)).strftime("%Y%m%d")

    cache = _cache_path(cache_dir, symbol, today)
    if _is_cache_valid(cache, max_age_hours):
        df = pd.read_parquet(cache)
    else:
        df = _retry(lambda: ak.stock_zh_index_daily_em(
            symbol=symbol, start_date=start, end_date=today
        ))
        df.to_parquet(cache)

    if df.empty:
        return pd.Series(dtype=float)

    date_col = "日期"
    close_col = "收盘"
    if date_col not in df.columns or close_col not in df.columns:
        return pd.Series(dtype=float)

    series = df.set_index(date_col)[close_col].astype(float)
    return series.tail(days)


def fetch_benchmark_data(
    cache_dir: str = ".cache",
    days: int = 120,
) -> dict[str, pd.Series]:
    """获取基准指数数据"""
    result = {}
    indices = {
        "hs300": "sh000300",
        "csi_bond": "sh000012",
    }
    for key, symbol in indices.items():
        try:
            result[key] = fetch_index_history(symbol, days, cache_dir)
            print(f"  获取基准 {key} ({symbol}) ...")
        except Exception as e:
            print(f"  警告: 获取基准 {key} 失败: {e}")
    return result
