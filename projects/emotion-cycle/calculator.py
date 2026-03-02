"""
Emotion Cycle Calculator
Core calculation: MA, CCI (20d), vol_ratio, ld_ratio, composite score → stage.

指标说明：
- CCI (20日)：对指数日线，20日比14日更平滑，业内情绪研究更常用
- 全市场成交额：沪深合计亿元，直接反映资金活跃度
- 涨停数：全市场绝对涨停家数，情绪温度计
- 涨跌停比（ld_ratio）：涨停数/跌停数，衡量多空力量
- 量能比（vol_ratio）：当日额/20日均额，判断放缩量

综合评分 (0~100)，加权平均后映射到 7 个情绪阶段。
"""

import os
import sys
import logging
from datetime import datetime
from typing import Optional, Dict, Tuple, List
import pandas as pd
import numpy as np

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent.parent))
from core.logging_cfg import get_logger
from config import CycleConfig, EmotionStage

logger = get_logger(__name__)


class EmotionCalculator:
    def __init__(self):
        self.ma_short = CycleConfig.MA_SHORT
        self.ma_mid   = CycleConfig.MA_MID
        self.ma_long  = CycleConfig.MA_LONG
        self.cci_period = CycleConfig.CCI_PERIOD   # 20

    # ─────────────────────────────────────────────
    # 基础指标计算
    # ─────────────────────────────────────────────

    def calculate_ma(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['ma_5']  = df['close'].rolling(5).mean()
        df['ma_10'] = df['close'].rolling(10).mean()
        df['ma_20'] = df['close'].rolling(20).mean()
        df['ma_position'] = (df['close'] - df['ma_20']) / df['ma_20'] * 100
        return df

    def calculate_cci(self, df: pd.DataFrame) -> pd.DataFrame:
        """CCI (20日)，业内对指数情绪分析的主流周期。"""
        df = df.copy()
        tp  = (df['high'] + df['low'] + df['close']) / 3
        sma = tp.rolling(self.cci_period).mean()
        mad = tp.rolling(self.cci_period).apply(
            lambda x: np.abs(x - x.mean()).mean(), raw=True
        )
        df['cci'] = (tp - sma) / (0.015 * mad)
        return df

    def calculate_vol_ratio(self, df: pd.DataFrame) -> pd.DataFrame:
        """量能比 = 当日成交额 / 20日均额。"""
        df = df.copy()
        df['amount_ma20'] = df['amount'].rolling(20).mean()
        df['vol_ratio'] = df['amount'] / df['amount_ma20'].replace(0, np.nan)
        return df

    def calculate_amount_trend(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['amount_ma5']  = df['amount'].rolling(5).mean()
        df['amount_ma10'] = df['amount'].rolling(10).mean()
        df['amount_trend'] = np.where(
            df['amount'] > df['amount_ma10'], 1,
            np.where(df['amount'] < df['amount_ma5'], -1, 0)
        )
        return df

    # ─────────────────────────────────────────────
    # 单指标评分（均映射到 0~100）
    # ─────────────────────────────────────────────

    def _score_cci(self, cci: float) -> float:
        """
        CCI → 0~100 分
        -150 → 0, 0 → 50, +150 → 100，线性插值，两端截断。
        """
        score = (cci + 150) / 300 * 100
        return float(np.clip(score, 0, 100))

    def _score_amount(self, amount_billion: float) -> float:
        """
        全市场成交额（亿元）→ 0~100 分
        参考区间：0→0分, 5000→20分, 12000→60分, 20000→100分（线性分段）
        """
        breakpoints = [0, 5000, 7000, 9000, 12000, 15000, 20000]
        scores      = [0,   20,   35,   50,    65,    80,   100]
        return float(np.interp(amount_billion, breakpoints, scores))

    def _score_limit_up(self, limit_up: int) -> float:
        """
        涨停数 → 0~100 分
        参考：0→0, 20→15, 100→50, 300→100（线性分段）
        """
        breakpoints = [0,  20,  50, 100, 150, 200, 300]
        scores      = [0,  15,  30,  50,  65,  80, 100]
        return float(np.interp(limit_up, breakpoints, scores))

    def _score_ld_ratio(self, ld_ratio: float) -> float:
        """
        涨跌停比 → 0~100 分
        0→10, 1→50, 3→75, 10→100
        """
        breakpoints = [0.0, 0.5,  1.0,  2.0,  3.0,  5.0, 10.0]
        scores      = [10,   25,   50,   65,   75,   90,  100]
        return float(np.interp(ld_ratio, breakpoints, scores))

    def composite_score(self, cci: float, amount: float,
                        limit_up: int, ld_ratio: float) -> float:
        """
        综合情绪评分 0~100（加权平均）
        权重：CCI 35%, 成交额 30%, 涨停数 20%, 涨跌停比 15%
        """
        s_cci    = self._score_cci(cci)
        s_amount = self._score_amount(amount)
        s_limit  = self._score_limit_up(limit_up)
        s_ld     = self._score_ld_ratio(ld_ratio)

        w = CycleConfig.WEIGHT_CCI, CycleConfig.WEIGHT_AMOUNT, \
            CycleConfig.WEIGHT_LIMIT_UP, CycleConfig.WEIGHT_LD_RATIO
        score = w[0]*s_cci + w[1]*s_amount + w[2]*s_limit + w[3]*s_ld
        return round(score, 1)

    # ─────────────────────────────────────────────
    # 综合评分 → 情绪阶段
    # ─────────────────────────────────────────────

    def score_to_stage(self, score: float) -> EmotionStage:
        """
        0~100 → 7 级情绪阶段（等宽分段）
        0~14  : frozen
        15~28 : cold
        29~42 : cool
        43~57 : neutral
        58~71 : warm
        72~85 : hot
        86~100: overheated
        """
        if score < 15:
            return EmotionStage.FROZEN
        elif score < 29:
            return EmotionStage.COLD
        elif score < 43:
            return EmotionStage.COOL
        elif score < 58:
            return EmotionStage.NEUTRAL
        elif score < 72:
            return EmotionStage.WARM
        elif score < 86:
            return EmotionStage.HOT
        else:
            return EmotionStage.OVERHEATED

    # ─────────────────────────────────────────────
    # 风控
    # ─────────────────────────────────────────────

    def calculate_risk_metrics(self, df: pd.DataFrame) -> Dict:
        if len(df) < 20:
            return {}
        recent = df.tail(20)
        max_high = recent['high'].max()
        current_close = recent['close'].iloc[-1]
        drawdown = (max_high - current_close) / max_high
        pct = recent['close'].pct_change().dropna()
        volatility = float(pct.std()) if len(pct) > 1 else 0.0
        trend = 'up' if recent['close'].iloc[-1] > recent['close'].iloc[0] else 'down'
        return {
            'drawdown': round(drawdown, 4),
            'volatility': round(volatility, 4),
            'trend': trend,
            'risk_level': 'high' if drawdown > CycleConfig.MAX_DRAWDOWN else 'normal',
        }

    # ─────────────────────────────────────────────
    # 主入口
    # ─────────────────────────────────────────────

    def analyze_emotion(self, ohlc_df: pd.DataFrame,
                        limit_stats: Dict,
                        market_amount: float) -> Dict:
        """
        Full emotion analysis.

        Parameters
        ----------
        ohlc_df      : 指数 OHLC（399101.SZ），用于 CCI / MA
        limit_stats  : fetch_limit_stats() 返回的 dict
                       {limit_up, limit_down, ld_ratio, limit_up_df}
        market_amount: 全市场成交额（沪深合计，亿元）
        """
        if ohlc_df.empty:
            return {}

        df = ohlc_df.copy()
        df = self.calculate_ma(df)
        df = self.calculate_cci(df)
        df = self.calculate_vol_ratio(df)
        df = self.calculate_amount_trend(df)

        latest = df.iloc[-1]
        cci       = float(latest.get('cci', 0) or 0)
        vol_ratio = float(latest.get('vol_ratio', 1) or 1)

        limit_up   = limit_stats.get('limit_up', 0)
        limit_down = limit_stats.get('limit_down', 0)
        ld_ratio   = limit_stats.get('ld_ratio', 1.0)

        # 综合评分
        score = self.composite_score(cci, market_amount, limit_up, ld_ratio)
        stage = self.score_to_stage(score)

        risk = self.calculate_risk_metrics(df)

        return {
            'trade_date':    latest['trade_date'],
            'close':         round(float(latest['close']), 2),
            'ma_position':   round(float(latest.get('ma_position', 0) or 0), 2),
            'cci':           round(cci, 2),
            'cci_period':    self.cci_period,
            'vol_ratio':     round(vol_ratio, 2),
            'market_amount': round(market_amount, 0),
            'limit_up':      limit_up,
            'limit_down':    limit_down,
            'ld_ratio':      ld_ratio,
            'score':         score,
            'cycle_tag':     stage.value,
            'amount_trend':  int(latest.get('amount_trend', 0) or 0),
            'risk':          risk,
            'history':       df,
        }


# ─────────────────────────────────────────────
# 信号生成
# ─────────────────────────────────────────────

class CycleSignal:
    def generate_signals(self, analysis: Dict) -> List[Dict]:
        signals = []
        if not analysis:
            return signals

        stage    = analysis.get('cycle_tag', 'neutral')
        cci      = analysis.get('cci', 0)
        score    = analysis.get('score', 50)
        ld_ratio = analysis.get('ld_ratio', 1.0)
        vol_ratio= analysis.get('vol_ratio', 1.0)
        risk     = analysis.get('risk', {})

        # 阶段信号
        if stage == EmotionStage.FROZEN.value:
            signals.append({
                'type': 'buy', 'signal': 'frozen_rebound',
                'reason': f'综合情绪评分极低({score})，市场冰点，关注超跌反弹机会',
                'strength': 0.9
            })
        elif stage == EmotionStage.COLD.value:
            signals.append({
                'type': 'buy', 'signal': 'cold_accumulate',
                'reason': f'情绪偏冷(评分{score})，可逢低布局',
                'strength': 0.7
            })
        elif stage == EmotionStage.HOT.value:
            signals.append({
                'type': 'sell', 'signal': 'hot_reduce',
                'reason': f'情绪火热(评分{score})，建议逐步减仓',
                'strength': 0.7
            })
        elif stage == EmotionStage.OVERHEATED.value:
            signals.append({
                'type': 'sell', 'signal': 'overheated_exit',
                'reason': f'情绪过热(评分{score})，注意追高风险',
                'strength': 0.9
            })

        # CCI 极值信号
        if cci > CycleConfig.CCI_EXTREME_BULL:
            signals.append({
                'type': 'sell', 'signal': 'cci_extreme_overbought',
                'reason': f'CCI={cci:.1f} 极度超买(>{CycleConfig.CCI_EXTREME_BULL})',
                'strength': 0.8
            })
        elif cci < CycleConfig.CCI_EXTREME_BEAR:
            signals.append({
                'type': 'buy', 'signal': 'cci_extreme_oversold',
                'reason': f'CCI={cci:.1f} 极度超卖(<{CycleConfig.CCI_EXTREME_BEAR})',
                'strength': 0.8
            })

        # 涨跌停比信号
        if ld_ratio >= CycleConfig.LD_RATIO_BULL:
            signals.append({
                'type': 'info', 'signal': 'ld_ratio_bull',
                'reason': f'涨跌停比={ld_ratio:.1f}，多头情绪占优',
                'strength': 0.6
            })
        elif ld_ratio <= CycleConfig.LD_RATIO_BEAR:
            signals.append({
                'type': 'warning', 'signal': 'ld_ratio_bear',
                'reason': f'涨跌停比={ld_ratio:.1f}，空头压制明显',
                'strength': 0.7
            })

        # 量能比信号
        if vol_ratio >= CycleConfig.VOL_RATIO_EXPAND:
            signals.append({
                'type': 'info', 'signal': 'volume_expand',
                'reason': f'量能比={vol_ratio:.2f}，放量明显（>1.5x均量）',
                'strength': 0.5
            })
        elif vol_ratio <= CycleConfig.VOL_RATIO_SHRINK:
            signals.append({
                'type': 'info', 'signal': 'volume_shrink',
                'reason': f'量能比={vol_ratio:.2f}，缩量明显（<0.7x均量）',
                'strength': 0.5
            })

        # 风控
        if risk.get('risk_level') == 'high':
            signals.append({
                'type': 'warning', 'signal': 'risk_alert',
                'reason': f"回撤 {risk.get('drawdown', 0):.1%}，超过风控阈值",
                'strength': 0.8
            })

        return signals


if __name__ == '__main__':
    from data_fetcher import EmotionDataFetcher
    import logging
    logging.basicConfig(level=logging.INFO)

    fetcher = EmotionDataFetcher()
    calc    = EmotionCalculator()
    trade_date = datetime.now().strftime('%Y%m%d')

    ohlc         = fetcher.fetch_880005_ohlc()
    limit_stats  = fetcher.fetch_limit_stats(trade_date)
    market_amount= fetcher.fetch_market_amount(trade_date)

    analysis = calc.analyze_emotion(ohlc, limit_stats, market_amount)

    print(f"Date      : {analysis['trade_date']}")
    print(f"Close     : {analysis['close']}")
    print(f"CCI({analysis['cci_period']}d) : {analysis['cci']}")
    print(f"Score     : {analysis['score']}")
    print(f"Stage     : {analysis['cycle_tag']}")
    print(f"Amount    : {analysis['market_amount']:.0f} 亿")
    print(f"LimitUp   : {analysis['limit_up']}")
    print(f"LimitDown : {analysis['limit_down']}")
    print(f"LD ratio  : {analysis['ld_ratio']}")
    print(f"Vol ratio : {analysis['vol_ratio']}")
