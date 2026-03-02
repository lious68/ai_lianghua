"""
Emotion Cycle Reporter
"""

import os
import sys
import logging
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd

sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent.parent))
from core.paths import Paths
from core.logging_cfg import get_logger

from config import EmotionStage

logger = get_logger(__name__)

REPORT_DIR = Paths.EmotionCycle.reports

_STAGE_NAME = {
    'frozen':     '冰点',
    'cold':       '寒冷',
    'cool':       '冷却',
    'neutral':    '中性',
    'warm':       '温暖',
    'hot':        '火热',
    'overheated': '过热',
}

_STAGE_TAG = {
    'frozen':     '[冰点]',
    'cold':       '[寒冷]',
    'cool':       '[冷却]',
    'neutral':    '[中性]',
    'warm':       '[温暖]',
    'hot':        '[火热]',
    'overheated': '[过热]',
}


class EmotionReporter:
    def __init__(self, bot_token: str = None, chat_ids: List[str] = None):
        self.bot_token = bot_token or os.getenv('TELEGRAM_BOT_TOKEN')
        raw = os.getenv('TELEGRAM_CHAT_IDS', '')
        self.chat_ids  = chat_ids or [c.strip() for c in raw.split(',') if c.strip()]

    def format_report(self, analysis: Dict, signals: List[Dict]) -> str:
        trade_date = str(analysis.get('trade_date', datetime.now().strftime('%Y-%m-%d')))
        stage      = analysis.get('cycle_tag', 'neutral')
        score      = analysis.get('score', 0)

        lines = []
        lines.append(f"{_STAGE_TAG.get(stage, '[?]')} 情绪周期日报")
        lines.append(f"日期: {trade_date}")
        lines.append("")

        # ── 综合评分 ──
        bar = self._score_bar(score)
        lines.append(f"【综合情绪评分】 {score:.1f}/100  {bar}")
        lines.append(f"  情绪阶段: {_STAGE_NAME.get(stage, '未知')}（{stage}）")
        lines.append("")

        # ── 指数状态 ──
        lines.append("【指数状态（399101 中小综指）】")
        lines.append(f"  收盘价   : {analysis.get('close', 0):.2f}")
        lines.append(f"  CCI({analysis.get('cci_period',20)}日) : {analysis.get('cci', 0):.2f}"
                     f"  {self._cci_label(analysis.get('cci', 0))}")
        lines.append(f"  MA20位置 : {analysis.get('ma_position', 0):+.2f}%")
        lines.append(f"  量能比   : {analysis.get('vol_ratio', 1):.2f}x"
                     f"  {self._vol_label(analysis.get('vol_ratio', 1))}")
        lines.append("")

        # ── 市场温度 ──
        lines.append("【全市场成交（沪深合计）】")
        lines.append(f"  成交额   : {analysis.get('market_amount', 0):.0f} 亿")
        lines.append(f"  涨停数   : {analysis.get('limit_up', 0)} 家")
        lines.append(f"  跌停数   : {analysis.get('limit_down', 0)} 家")
        ld = analysis.get('ld_ratio', 0)
        lines.append(f"  涨跌停比 : {ld:.2f}  {self._ld_label(ld)}")
        lines.append("")

        # ── 信号 ──
        if signals:
            lines.append("【信号】")
            for s in signals:
                tag = {'buy': '[买入]', 'sell': '[卖出]',
                       'warning': '[警告]', 'info': '[提示]'}.get(s['type'], '[  ]')
                lines.append(f"  {tag} {s['signal']}: {s['reason']}")
            lines.append("")

        # ── 风控 ──
        risk = analysis.get('risk', {})
        if risk:
            rlevel = risk.get('risk_level', 'normal')
            rtag   = '[高风险]' if rlevel == 'high' else '[正常]'
            lines.append(f"【风控状态】{rtag}")
            lines.append(f"  回撤: {risk.get('drawdown', 0):.2%}  "
                         f"趋势: {risk.get('trend', '-')}  "
                         f"波动率: {risk.get('volatility', 0):.4f}")

        return "\n".join(lines)

    # ── 辅助标签 ──

    def _score_bar(self, score: float, width: int = 20) -> str:
        filled = int(score / 100 * width)
        return "[" + "#" * filled + "-" * (width - filled) + "]"

    def _cci_label(self, cci: float) -> str:
        from config import CycleConfig as C
        if cci > C.CCI_EXTREME_BULL:  return "极度超买"
        if cci > C.CCI_OVERBOUGHT:    return "超买"
        if cci > C.CCI_MILD_BULL:     return "偏强"
        if cci > -C.CCI_MILD_BULL:    return "中性"
        if cci > C.CCI_OVERSOLD:      return "偏弱"
        if cci > C.CCI_EXTREME_BEAR:  return "超卖"
        return "极度超卖"

    def _ld_label(self, ratio: float) -> str:
        from config import CycleConfig as C
        if ratio >= C.LD_RATIO_BULL:    return "多头明显占优"
        if ratio >= C.LD_RATIO_NEUTRAL: return "多空均衡"
        if ratio >= C.LD_RATIO_BEAR:    return "偏空"
        return "空头压制"

    def _vol_label(self, ratio: float) -> str:
        from config import CycleConfig as C
        if ratio >= C.VOL_RATIO_EXPAND: return "放量"
        if ratio >= C.VOL_RATIO_NORMAL: return "正常"
        if ratio >= C.VOL_RATIO_SHRINK: return "温和缩量"
        return "明显缩量"

    # ── 发送 / 保存 ──

    def send_report(self, message: str):
        if not self.bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN not configured")
            return
        try:
            import requests
            for chat_id in self.chat_ids:
                url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
                resp = requests.post(url, json={
                    'chat_id': chat_id,
                    'text': message,
                    'parse_mode': 'Markdown'
                }, timeout=10)
                if resp.status_code == 200:
                    logger.info(f"Report sent to {chat_id}")
                else:
                    logger.error(f"Failed to send: {resp.text}")
        except Exception as e:
            logger.error(f"Failed to send report: {e}")

    def save_report(self, message: str, trade_date: str):
        import pathlib
        report_dir = pathlib.Path(REPORT_DIR)
        report_dir.mkdir(parents=True, exist_ok=True)
        filepath = report_dir / f"emotion_{trade_date}.md"
        filepath.write_text(message, encoding='utf-8')
        logger.info(f"Report saved → {filepath}")
