#!/usr/bin/env python3
"""
Emotion Cycle System - Main Entry Point
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

# ── core 路径注入（消除 sys.path hack）──
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from core.paths import Paths
from core.logging_cfg import setup_logging, get_logger

setup_logging(project="emotion-cycle")
logger = get_logger(__name__)

from data_fetcher import EmotionDataFetcher
from calculator import EmotionCalculator, CycleSignal
from reporter import EmotionReporter


def get_last_trading_date(before: str = None) -> str:
    """
    返回 before 日期（含）当天或之前最近一个交易日。
    若 before 本身是交易日直接返回，否则往前找，最多查 15 天（覆盖春节等长假）。
    """
    import os
    try:
        import tushare as ts
        from dotenv import load_dotenv
        load_dotenv()
        token = os.getenv('TUSHARE_TOKEN')
        if not token:
            return before or datetime.now().strftime('%Y%m%d')
        pro = ts.pro_api(token)
        before = before or datetime.now().strftime('%Y%m%d')
        start = (datetime.strptime(before, '%Y%m%d') - timedelta(days=15)).strftime('%Y%m%d')
        cal = pro.trade_cal(exchange='SSE', start_date=start, end_date=before)
        open_days = sorted(cal[cal['is_open'] == 1]['cal_date'].tolist())
        if not open_days:
            return before
        result = open_days[-1]
        if result != before:
            logger.info(f"{before} 非交易日，使用最近交易日 {result}")
        return result
    except Exception as e:
        logger.warning(f"get_last_trading_date failed: {e}, fallback to today")
        return before or datetime.now().strftime('%Y%m%d')


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Emotion Cycle System')
    parser.add_argument('--date', type=str, help='Trade date (YYYYMMDD)')
    parser.add_argument('--send', action='store_true', help='Send report via Telegram')
    parser.add_argument('--save', action='store_true', default=True,
                        help='Save report to file (default: True)')
    args = parser.parse_args()

    # 若未指定日期，自动取今天；若今天非交易日，退回到最近一个交易日
    trade_date = get_last_trading_date(args.date or datetime.now().strftime('%Y%m%d'))
    logger.info(f"Starting emotion cycle analysis for {trade_date}")

    fetcher    = EmotionDataFetcher()
    calculator = EmotionCalculator()
    signal_gen = CycleSignal()
    reporter   = EmotionReporter()

    # ── 数据获取 ──
    logger.info("Fetching OHLC...")
    ohlc = fetcher.fetch_880005_ohlc()

    logger.info("Fetching limit stats...")
    limit_stats = fetcher.fetch_limit_stats(trade_date)

    logger.info("Fetching market amount...")
    market_amount = fetcher.fetch_market_amount(trade_date)

    # ── 分析 ──
    logger.info("Analyzing...")
    analysis = calculator.analyze_emotion(ohlc, limit_stats, market_amount)
    signals  = signal_gen.generate_signals(analysis)

    message = reporter.format_report(analysis, signals)

    print("\n" + "=" * 55)
    print(message)
    print("=" * 55 + "\n")

    # ── 保存 ──
    if args.save:
        reporter.save_report(message, trade_date)

        summary_row = pd.DataFrame([{
            'trade_date':    trade_date,
            'close':         analysis.get('close'),
            'cci':           analysis.get('cci'),
            'cci_period':    analysis.get('cci_period'),
            'ma_position':   analysis.get('ma_position'),
            'market_amount': analysis.get('market_amount'),
            'limit_up':      analysis.get('limit_up'),
            'limit_down':    analysis.get('limit_down'),
            'ld_ratio':      analysis.get('ld_ratio'),
            'vol_ratio':     analysis.get('vol_ratio'),
            'score':         analysis.get('score'),
            'cycle_tag':     analysis.get('cycle_tag'),
            'amount_trend':  analysis.get('amount_trend'),
            'risk_level':    analysis.get('risk', {}).get('risk_level'),
            'drawdown':      analysis.get('risk', {}).get('drawdown'),
            'trend':         analysis.get('risk', {}).get('trend'),
        }])
        fetcher.save_emotion_history(summary_row)

    if args.send:
        logger.info("Sending report via Telegram...")
        reporter.send_report(message)

    logger.info("Emotion cycle analysis completed")


if __name__ == '__main__':
    main()
