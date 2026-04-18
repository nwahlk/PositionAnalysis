"""Markdown 表格解析器 - 将 Obsidian 持仓文件转换为结构化数据"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FundPosition:
    """基金持仓"""
    code: str
    name: str
    shares: float
    cost_nav: float | None       # 成本净值，未知为 None
    buy_date: str


@dataclass
class StockPosition:
    """股票持仓"""
    code: str
    name: str
    shares: int
    cost_price: float | None     # 成本价，未知为 None
    buy_date: str


@dataclass
class DepositPosition:
    """存款"""
    name: str
    amount: float
    annual_rate: float
    maturity: str


@dataclass
class WealthPosition:
    """理财产品"""
    name: str
    amount: float
    annual_rate: float
    buy_date: str
    maturity: str


@dataclass
class PositionSnapshot:
    """一个时间点的完整持仓快照"""
    date: str
    funds: list[FundPosition] = field(default_factory=list)
    stocks: list[StockPosition] = field(default_factory=list)
    deposits: list[DepositPosition] = field(default_factory=list)
    wealth_products: list[WealthPosition] = field(default_factory=list)


def parse_markdown_file(filepath: str | Path) -> PositionSnapshot:
    """解析单个 Markdown 持仓文件"""
    content = Path(filepath).read_text(encoding="utf-8")

    # 从 H1 标题提取日期
    date = _extract_date(content, filepath)

    # 按章节拆分
    sections = _split_sections(content)

    snapshot = PositionSnapshot(date=date)
    section_map = {
        "基金": ("funds", _parse_funds),
        "股票": ("stocks", _parse_stocks),
        "存款": ("deposits", _parse_deposits),
        "理财": ("wealth_products", _parse_wealth),
    }
    for section_name, (attr, parser) in section_map.items():
        if section_name in sections:
            setattr(snapshot, attr, parser(sections[section_name]))

    return snapshot


def parse_all_files(data_dir: str | Path) -> list[PositionSnapshot]:
    """解析目录下所有持仓文件，按日期排序"""
    dir_path = Path(data_dir)
    if not dir_path.exists():
        return []

    snapshots = []
    for f in sorted(dir_path.glob("持仓记录_*.md")):
        try:
            snapshots.append(parse_markdown_file(f))
        except Exception as e:
            print(f"警告: 解析 {f.name} 失败: {e}")

    snapshots.sort(key=lambda s: s.date)
    return snapshots


def _extract_date(content: str, filepath: Path) -> str:
    """从 H1 标题或文件名提取日期"""
    # 优先从 H1 标题提取
    m = re.search(r"#\s*持仓记录\s*(\d{4}-\d{2}-\d{2})", content)
    if m:
        return m.group(1)

    # 回退到文件名
    m = re.search(r"(\d{4}-\d{2}-\d{2})", filepath.stem)
    if m:
        return m.group(1)

    return filepath.stem


def _split_sections(content: str) -> dict[str, str]:
    """按 ## 标题拆分内容为各章节"""
    sections: dict[str, str] = {}
    current_section = None
    lines: list[str] = []

    for line in content.splitlines():
        m = re.match(r"^##\s+(.+)$", line.strip())
        if m:
            if current_section and lines:
                sections[current_section] = "\n".join(lines)
            current_section = m.group(1).strip()
            lines = []
        elif current_section:
            lines.append(line)

    if current_section and lines:
        sections[current_section] = "\n".join(lines)

    return sections


def _parse_table_rows(section_text: str) -> list[list[str]]:
    """从章节文本中提取表格行（跳过表头和分隔行）"""
    rows = []
    for line in section_text.strip().splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        # 跳过分隔行（|---|---|）
        if re.match(r"^\|[\s\-:]+\|", line):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if cells and cells[0]:
            rows.append(cells)
    return rows[1:]  # 跳过表头行


def _safe_float(v: str) -> float | None:
    """安全转 float，空值返回 None"""
    if not v or not v.strip():
        return None
    try:
        return float(v.strip())
    except ValueError:
        return None


def _parse_funds(section: str) -> list[FundPosition]:
    rows = _parse_table_rows(section)
    result = []
    for row in rows:
        if len(row) < 3:
            continue
        shares = _safe_float(row[2])
        if shares is None or shares <= 0:
            continue
        result.append(FundPosition(
            code=row[0],
            name=row[1],
            shares=shares,
            cost_nav=_safe_float(row[3]) if len(row) > 3 else None,
            buy_date=row[4].strip() if len(row) > 4 else "",
        ))
    return result


def _parse_stocks(section: str) -> list[StockPosition]:
    rows = _parse_table_rows(section)
    result = []
    for row in rows:
        if len(row) < 3:
            continue
        shares = _safe_float(row[2])
        if shares is None or shares <= 0:
            continue
        result.append(StockPosition(
            code=row[0],
            name=row[1],
            shares=int(shares),
            cost_price=_safe_float(row[3]) if len(row) > 3 else None,
            buy_date=row[4].strip() if len(row) > 4 else "",
        ))
    return result


def _parse_deposits(section: str) -> list[DepositPosition]:
    rows = _parse_table_rows(section)
    result = []
    for row in rows:
        if len(row) < 4 or not row[0].strip():
            continue
        amount = _safe_float(row[1])
        if amount is None or amount <= 0:
            continue
        rate = _safe_float(row[2].replace("%", ""))
        result.append(DepositPosition(
            name=row[0].strip(),
            amount=amount,
            annual_rate=rate / 100 if rate else 0.0,
            maturity=row[3].strip() if len(row) > 3 else "",
        ))
    return result


def _parse_wealth(section: str) -> list[WealthPosition]:
    rows = _parse_table_rows(section)
    result = []
    for row in rows:
        if len(row) < 3 or not row[0].strip():
            continue
        amount = _safe_float(row[1])
        if amount is None or amount <= 0:
            continue
        rate = _safe_float(row[2].replace("%", ""))
        result.append(WealthPosition(
            name=row[0].strip(),
            amount=amount,
            annual_rate=rate / 100 if rate else 0.0,
            buy_date=row[3].strip() if len(row) > 3 else "",
            maturity=row[4].strip() if len(row) > 4 else "",
        ))
    return result
