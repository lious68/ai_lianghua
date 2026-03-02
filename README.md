# OpenClaw

A股量化分析系统，模块化架构，涵盖个股强度排名、情绪周期诊断、价格预测、形态扫描与市场分析。

---

## 目录结构

```
ai_lianghua/
├── core/                        # 全局基础设施层（唯一路径中心 + 统一 logging）
│   ├── __init__.py
│   ├── paths.py                 # 所有路径定义，其他模块统一从这里取
│   └── logging_cfg.py           # 统一 logging 配置
│
├── data/                        # 所有运行时数据（按项目隔离，代码目录不存数据）
│   ├── alpha-oracle/            # alpha_oracle.db
│   ├── emotion-cycle/           # emotion_history.csv、reports/
│   ├── stock-rps/               # rps.db
│   ├── vcp-scanner/             # vcp.db
│   └── market-analysis/         # reports/
│
├── projects/                    # 各业务项目（纯代码，不含数据）
│   ├── stock-rps/               # 个股/板块 RPS 排名系统
│   ├── alpha-oracle/            # 股价预测 + 板块共振
│   ├── emotion-cycle/           # 市场情绪周期诊断
│   ├── vcp-scanner/             # VCP 形态扫描
│   ├── market-analysis/         # 技术分析日报
│   ├── stock-screeners/         # 多策略选股
│   └── ice-point-resonance/     # 冰点共振预警
│
├── skills/                      # 可复用底层能力库
│   ├── modelverse/              # UCloud ModelVerse AI 客户端
│   ├── stock-analysis-toolkit/  # 量化指标工具集
│   ├── financial-analysis-pro/  # 财务分析（DCF、三张报表）
│   ├── tavily/                  # 网络搜索
│   └── zhipu/                   # 智谱 AI 客户端
│
├── openclaw_config.py           # 兼容旧接口的 shim，代理到 core.paths
├── .env                         # API Key 配置（不提交）
└── requirements.txt
```

### 分层原则（MECE）

| 层 | 目录 | 职责 | 可以依赖 |
|---|---|---|---|
| 基础设施 | `core/` | 路径、logging，无业务逻辑 | 标准库 |
| 能力库 | `skills/` | 可复用的 API 封装、工具函数 | `core/` |
| 业务项目 | `projects/` | 具体策略与分析逻辑 | `core/`、`skills/` |
| 数据 | `data/` | 运行时产物，不含代码 | — |

> **规则**：`projects/` 下的代码不直接写路径字符串，一律通过 `core.paths.Paths` 获取。

---

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API Key
cp .env.example .env
# 编辑 .env，填入 TUSHARE_TOKEN 等

# 3. 初始化数据目录
python core/paths.py
```

---

## 项目说明

### stock-rps — 个股/板块 RPS 排名

**用途：** 计算股票相对强弱排名（Relative Performance Strength），识别持续强势的个股和板块，思路来自 Minervini / 欧奈尔。

**目录结构：**

```
projects/stock-rps/
├── main_update.py               # 个股 RPS 主流程
├── board/
│   └── send_report.py           # 板块 RPS 计算与报告
├── amount_ranking/
│   └── incremental_update.py    # 成交额 Top500 排名
└── financial/                   # 预留：财务指标过滤
```

**RPS 计算逻辑：**

```
N 日涨幅 = (今日收盘 - N 日前收盘) / N 日前收盘
RPS_N    = 该股 N 日涨幅在全体股票中的百分位 × 100（0~100，越高越强）
综合 RPS = RPS_10×40% + RPS_20×20% + RPS_50×20% + RPS_120×20%
```

| 周期 | 含义 | 权重 |
|---|---|---|
| RPS_10 | 近 2 周动量 | 40% |
| RPS_20 | 近 1 月趋势 | 20% |
| RPS_50 | 近季度趋势 | 20% |
| RPS_120 | 近半年趋势 | 20% |

**用法：**

```bash
# 计算科创板个股 RPS（默认上一交易日，约 90 秒）
python projects/stock-rps/main_update.py

# 指定日期 + 刷新股票基本信息
python projects/stock-rps/main_update.py --date 20260227 --basic

# 全市场（耗时较长）
python projects/stock-rps/main_update.py --market all

# 板块 RPS 日报（按行业聚合）
python projects/stock-rps/board/send_report.py --date 20260227 --days 30

# 成交额排名
python projects/stock-rps/amount_ranking/incremental_update.py --date 20260227
```

**DB 查询示例：**

```sql
-- 科创板四维强势股（RPS 全面 > 90）
SELECT r.ts_code, s.name, s.industry,
       r.rps_combo, r.rps_10, r.rps_20, r.rps_50, r.rps_120,
       r.close, r.pct_chg
FROM rps_daily r
LEFT JOIN stock_basic s ON r.ts_code = s.ts_code
WHERE r.trade_date = '20260227'
  AND r.rps_10 > 90 AND r.rps_20 > 90
  AND r.rps_50 > 85 AND r.rps_120 > 85
ORDER BY r.rps_combo DESC;
```

**数据表：**

| 表 | 内容 |
|---|---|
| `rps_daily` | 个股每日 RPS：`trade_date, ts_code, rps_10/20/50/120, rps_combo, close, pct_chg` |
| `board_daily_prices` | 板块每日数据：`ts_code(行业名), trade_date, close, pct_chg, amount` |
| `amount_ranking` | 成交额 Top500：`trade_date, rank, ts_code, amount(亿元), close, pct_chg` |
| `stock_basic` | 股票基本信息缓存：`ts_code, name, industry, list_date` |

---

### emotion-cycle — 市场情绪周期诊断

**用途：** 综合 CCI、全市场成交额、涨停数、涨跌停比，给出当日市场情绪阶段（冰点→过热），辅助择时。

**指标体系：**

| 指标 | 数据来源 | 权重 | 说明 |
|---|---|---|---|
| CCI(20日) | 399101.SZ 中小综指 | 35% | 20日比14日更平滑，业内指数情绪分析主流周期 |
| 全市场成交额 | 沪深合计（亿元） | 30% | <5000亿冷，>20000亿过热 |
| 涨停数 | 全市场 pct_chg≥9.5% | 20% | <20家极冷，>300家过热 |
| 涨跌停比 | 涨停数/跌停数 | 15% | >3多头占优，<0.5空头压制 |

**情绪阶段（综合评分 0~100）：**

```
0~14  : 冰点（frozen）   → 超跌反弹机会
15~28 : 寒冷（cold）     → 可逢低布局
29~42 : 冷却（cool）
43~57 : 中性（neutral）
58~71 : 温暖（warm）
72~85 : 火热（hot）      → 建议逐步减仓
86~100: 过热（overheated）→ 注意追高风险
```

**用法：**

```bash
# 当日情绪分析（今天是非交易日则用最近交易日数据）
python projects/emotion-cycle/main.py

# 指定日期
python projects/emotion-cycle/main.py --date 20260227
```

**输出文件：**

```
data/emotion-cycle/
├── emotion_history.csv      # 每日情绪摘要（trade_date, score, cycle_tag, cci, ...）
└── reports/
    └── emotion_20260227.md  # 当日完整分析报告
```

---

### alpha-oracle — 股价预测 + 板块共振

**用途：** 对单只或批量股票做未来 30 日价格预测，并检测当日板块共振信号。

**预测逻辑：** 优先使用 Google TimesFM 模型（需单独安装）；未安装时 fallback 为基于线性回归的统计趋势外推，并给出 1.5σ 置信区间。

**用法：**

```bash
# 单股深度预测（逐日明细 + 板块共振）
python projects/alpha-oracle/alpha_oracle.py --predict 688111.SH

# 批量扫描科创板（默认）
python projects/alpha-oracle/alpha_oracle.py

# 扫描沪深 300 前 100 只
python projects/alpha-oracle/alpha_oracle.py --market hs300 --top 100

# 扫描科创 50 指数成分
python projects/alpha-oracle/alpha_oracle.py --market kc50
```

**DB 字段（`data/alpha-oracle/alpha_oracle.db`，表 `alpha_results`）：**

| 字段 | 含义 |
|---|---|
| `scan_date` | 扫描日期 |
| `ts_code` | 股票代码 |
| `current_price` | 当日收盘价 |
| `predicted_mean` | 未来 30 日预测均价 |
| `predicted_change` | 预测涨跌幅（%） |
| `signal` | bullish(>+5%) / bearish(<-5%) / neutral |
| `resonance_type` | 板块共振：strong_up / weak_up / neutral / weak_down / strong_down |
| `resonance_confidence` | 共振置信度（0~2，越高越强） |
| `positive_ratio` | 当日上涨板块占比（0~1） |

---

### vcp-scanner — VCP 形态扫描

**用途：** 扫描符合 Minervini VCP（波动收缩形态）标准的个股，识别低风险买点。

**用法：**

```bash
python projects/vcp-scanner/main.py
```

**DB 字段（`data/vcp-scanner/vcp.db`，表 `vcp_results`）：**

| 字段 | 含义 |
|---|---|
| `dist_from_high` | 距 52 周高点跌幅 %（越小越靠近高位） |
| `contraction_pct` | 最后一次波段收缩幅度 % |
| `tightness` | 紧致度：近10日振幅相对近60日的压缩比 |
| `vol_shrinking` | 成交量是否萎缩（1=是） |
| `score` | 综合评分 0~100 |

---

### 其他项目

| 项目 | 说明 | 入口 |
|---|---|---|
| `market-analysis` | 市场技术分析日报（MACD 背离等） | `daily_report_automation.py` |
| `stock-screeners/net-profit-gap` | 净利润缺口扫描 | `main.py` |
| `stock-screeners/signal_tracker` | 交易信号跟踪 | `updater.py` |
| `ice-point-resonance` | 市场冰点共振预警，复用 emotion-cycle 数据 | `alert_report.py` |

---

## 配置项（.env）

| 变量 | 必填 | 说明 |
|---|---|---|
| `TUSHARE_TOKEN` | 是 | Tushare Pro API Token，所有数据拉取依赖此项 |
| `TELEGRAM_BOT_TOKEN` | 否 | Telegram Bot Token，用于报告推送 |
| `TAVILY_API_KEY` | 否 | Tavily 搜索，用于 AI 情报周报 |
| `UMODELVERSE_API_KEY` | 否 | UCloud ModelVerse，用于 AI 分析 |

---

## 新增项目规范

```python
# 1. 在 core/paths.py 的 Paths 类中添加
class MyProject:
    data    = ROOT / "data" / "my-project"
    db      = ROOT / "data" / "my-project" / "my.db"
    reports = ROOT / "data" / "my-project" / "reports"

# 2. 入口文件顶部
from core.paths import Paths
from core.logging_cfg import setup_logging, get_logger
setup_logging(project="my-project")
logger = get_logger(__name__)

# 3. 使用路径
db_path = Paths.MyProject.db
```

---

## License

MIT
