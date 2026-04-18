# 持仓分析报告 {{ date }}

> 数据日期：{{ date }} | 生成时间：{{ gen_time }}

---

## 投资建议

**{{ advice_summary }}**

{% if advice_actions %}
**操作建议：**
{% for a in advice_actions -%}
- {{ a }}
{% endfor %}
{% endif %}

{% if risk_warnings %}
**风险提示：**
{% for w in risk_warnings -%}
- ⚠️ {{ w }}
{% endfor %}
{% endif %}

{% if not advice_actions and not risk_warnings %}
- 当前无需操作，建议每月复查持仓
{% endif %}

---

## 组合概览

| 总资产 | 总盈亏 | 持仓分散度 | 资产数量 |
|:------:|:------:|:------:|:------:|
| {{ total_value }} | {{ total_profit }} ({{ total_profit_pct }}) | {{ diversification_score }} ({{ diversification_hint }}) | {{ asset_count }} ({{ asset_detail }}) |

### 资产配置

```mermaid
pie title 资产配置
{% for item in allocation_mermaid -%}
    "{{ item.label }}" : {{ item.value }}
{% endfor %}
```

---

{% if funds %}
## 基金持仓分析

| 代码 | 名称 | 盈亏 | 收益率 | 近1月 | 近3月 | 排名 | 夏普 | 回撤 | 波动率 | 建议 | 分析理由 |
|:----:|:-----|-----:|------:|------:|------:|-----:|-----:|-----:|------:|:----:|:---------|
{% for f in funds -%}
| {{ f.code }} | {{ f.name }} | {{ f.profit_str }} | {{ f.profit_pct_str }} | {{ f.ret_1m }} | {{ f.ret_3m }} | {{ f.rank_pct_str }} | {{ f.sharpe_str }} | {{ f.max_drawdown_str }} | {{ f.volatility }} | {{ f.rec_emoji }} {{ f.recommendation }} | {{ f.reason }} |
{% endfor %}
{% endif %}

{% if stocks %}
## 股票持仓分析

| 代码 | 名称 | 盈亏 | 收益率 | 近1月 | 近3月 | RSI | PB | 波动率 | 建议 | 分析理由 |
|:----:|:-----|-----:|------:|------:|------:|:---:|:--:|------:|:----:|:---------|
{% for s in stocks -%}
| {{ s.code }} | {{ s.name }} | {{ s.profit_str }} | {{ s.profit_pct_str }} | {{ s.ret_1m }} | {{ s.ret_3m }} | {{ s.rsi_str }} | {{ s.pb_str }} | {{ s.volatility }} | {{ s.rec_emoji }} {{ s.recommendation }} | {{ s.reason }} |
{% endfor %}
{% endif %}

{% if deposits %}
## 存款

| 名称 | 金额 | 年化利率 | 到期日 | 到期本息 |
|:-----|-----:|:------:|:------:|--------:|
{% for d in deposits -%}
| {{ d.name }} | {{ d.amount_str }} | {{ d.rate_str }} | {{ d.maturity }} | {{ d.total_str }} |
{% endfor %}
{% endif %}

{% if wealth %}
## 理财产品

| 名称 | 金额 | 年化利率 | 买入日 | 到期日 | 已持有天数 | 到期本息 |
|:-----|-----:|:------:|:------:|:------:|:------:|--------:|
{% for w in wealth -%}
| {{ w.name }} | {{ w.amount_str }} | {{ w.rate_str }} | {{ w.buy_date }} | {{ w.maturity }} | {{ w.days_held }} | {{ w.total_str }} |
{% endfor %}
{% endif %}

---

*本报告仅供参考，不构成投资建议。投资有风险，入市需谨慎。*
