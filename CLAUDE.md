# 项目说明

持仓分析 CLI 工具，基于支付宝导出的持仓数据生成投资分析报告。

## 快捷指令

当用户说"持仓分析"、"分析持仓"、"跑一下分析"、"分析一下"等类似意图时，直接执行：

```
pa analyze --no-open
```

然后读取生成的 Markdown 报告，展示投资建议摘要和需要关注的标的。

## 技术栈

- Python CLI（Click）
- 数据源：akshare（基金/股票行情）
- 报告：Jinja2 模板 → Markdown + HTML（Plotly 图表）
- 持仓数据：Obsidian vault 中的 Markdown 文件
