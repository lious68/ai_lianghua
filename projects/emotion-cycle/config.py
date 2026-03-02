"""
Emotion Cycle Configuration
Market emotion cycle thresholds and constants

指标体系说明（业内主流 A 股量化实践）：

1. CCI (20日)
   对指数日线，20日 CCI 比 14日更平滑，在量化情绪研究中更常用。
   阈值：>+100 超买区（过热），<-100 超卖区（冰点），0 为中轴。

2. 全市场成交额（沪深两市合计，单位：亿元）
   参考历史均值分级：
   - <5000亿：极度萎缩，市场冰点
   - 5000~7000亿：偏冷
   - 7000~9000亿：温和
   - 9000~12000亿：中性活跃
   - 12000~15000亿：偏热
   - 15000~20000亿：火热
   - >20000亿：过热/疯狂
   （2024-2025年 A 股日均成交约 1.2 万亿，2024年10月高峰超3万亿）

3. 涨停数（绝对数）
   比涨停比例更直观，常用参考：
   - <20：极冷
   - 20~50：偏冷
   - 50~100：温和
   - 100~150：中性
   - 150~200：偏热
   - 200~300：火热
   - >300：过热

4. 涨跌停比（涨停数 / max(跌停数,1)）
   衡量多空力量对比，>3 看多情绪强，<0.5 看空情绪强

5. 量能比（当日成交额 / 20日均额）
   >1.5 明显放量，<0.7 明显缩量
"""

from enum import Enum


class EmotionStage(Enum):
    FROZEN = "frozen"        # 冰点
    COLD = "cold"            # 寒冷
    COOL = "cool"            # 冷却
    NEUTRAL = "neutral"      # 中性
    WARM = "warm"            # 温暖
    HOT = "hot"              # 火热
    OVERHEATED = "overheated"  # 过热


class CycleConfig:
    # ── CCI 周期与阈值 ──
    CCI_PERIOD = 20           # 20日，比14日更平滑，业内指数情绪分析更常用
    CCI_EXTREME_BEAR = -150   # 极度超卖
    CCI_OVERSOLD = -100       # 超卖
    CCI_MILD_BEAR = -50       # 偏弱
    CCI_MILD_BULL = 50        # 偏强
    CCI_OVERBOUGHT = 100      # 超买
    CCI_EXTREME_BULL = 150    # 极度超买

    # ── MA 周期 ──
    MA_SHORT = 5
    MA_MID = 10
    MA_LONG = 20

    # ── 全市场成交额阈值（沪深合计，单位：亿元）──
    AMOUNT_FROZEN     = 5000    # <5000亿：冰点
    AMOUNT_COLD       = 7000    # 5000~7000亿：偏冷
    AMOUNT_COOL       = 9000    # 7000~9000亿：温和
    AMOUNT_NEUTRAL    = 12000   # 9000~12000亿：中性
    AMOUNT_WARM       = 15000   # 12000~15000亿：偏热
    AMOUNT_HOT        = 20000   # 15000~20000亿：火热
    # >20000亿：过热

    # ── 涨停数阈值（绝对数，全市场 pct_chg >= 9.9%）──
    LIMIT_UP_FROZEN      = 20    # <20家：极冷
    LIMIT_UP_COLD        = 50    # 20~50家：偏冷
    LIMIT_UP_COOL        = 100   # 50~100家：温和
    LIMIT_UP_NEUTRAL     = 150   # 100~150家：中性
    LIMIT_UP_WARM        = 200   # 150~200家：偏热
    LIMIT_UP_HOT         = 300   # 200~300家：火热
    # >300家：过热

    # ── 涨跌停比阈值（涨停数 / max(跌停数,1)）──
    LD_RATIO_BEAR    = 0.5    # <0.5：明显偏空
    LD_RATIO_NEUTRAL = 1.5    # 0.5~1.5：多空平衡
    LD_RATIO_BULL    = 3.0    # >3：明显偏多

    # ── 量能比阈值（当日额 / 20日均额）──
    VOL_RATIO_SHRINK  = 0.7   # <0.7：明显缩量
    VOL_RATIO_NORMAL  = 1.2   # 0.7~1.2：正常
    VOL_RATIO_EXPAND  = 1.5   # >1.5：明显放量

    # ── 风控 ──
    MAX_DRAWDOWN    = 0.08
    STOP_LOSS_RATIO = 0.05

    # ── 各指标权重（用于综合评分 0~100）──
    WEIGHT_CCI       = 0.35
    WEIGHT_AMOUNT    = 0.30
    WEIGHT_LIMIT_UP  = 0.20
    WEIGHT_LD_RATIO  = 0.15
