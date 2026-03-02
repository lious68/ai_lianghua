"""
Board RPS Module
Calculate sector (申万一级) daily RPS and report top performers.

板块 RPS 逻辑：
  - 拉取申万一级行业指数当日涨跌幅（pct_chg）
  - 在所有板块间做百分位排名 × 100 = 板块 RPS
  - 同时记录连续 N 日的累计涨幅排名
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pandas as pd
import sqlite3

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()

from core.paths import Paths
from core.logging_cfg import get_logger

logger = get_logger(__name__)

DB_PATH = Paths.StockRps.db

# 申万一级行业指数代码
SW_L1_CODES = [
    '801010.SI', '801020.SI', '801030.SI', '801040.SI', '801050.SI',
    '801080.SI', '801110.SI', '801120.SI', '801130.SI', '801140.SI',
    '801150.SI', '801160.SI', '801170.SI', '801180.SI', '801200.SI',
    '801210.SI', '801230.SI', '801710.SI', '801720.SI', '801730.SI',
    '801740.SI', '801750.SI', '801760.SI', '801770.SI', '801780.SI',
    '801790.SI', '801880.SI', '801890.SI',
]

SW_L1_NAMES = {
    '801010.SI': '农林牧渔', '801020.SI': '采掘',    '801030.SI': '化工',
    '801040.SI': '钢铁',    '801050.SI': '有色金属', '801080.SI': '电子',
    '801110.SI': '家用电器', '801120.SI': '食品饮料', '801130.SI': '纺织服装',
    '801140.SI': '轻工制造', '801150.SI': '医药生物', '801160.SI': '公用事业',
    '801170.SI': '交通运输', '801180.SI': '房地产',  '801200.SI': '商业贸易',
    '801210.SI': '休闲服务', '801230.SI': '综合',    '801710.SI': '建筑材料',
    '801720.SI': '建筑装饰', '801730.SI': '电气设备', '801740.SI': '国防军工',
    '801750.SI': '计算机',  '801760.SI': '传媒',    '801770.SI': '通信',
    '801780.SI': '银行',    '801790.SI': '非银金融', '801880.SI': '汽车',
    '801890.SI': '机械设备',
}


# ─────────────────────────────────────────────
# Data Fetching
# ─────────────────────────────────────────────

def fetch_board_daily(trade_date: str, days: int = 60) -> pd.DataFrame:
    """
    拉取行业板块数据。
    策略：用 stock_basic.industry + daily 日线聚合，
    计算每个申万行业的平均涨跌幅和合计成交额，作为板块代理数据。
    返回列：ts_code(industry), trade_date, close(weighted), pct_chg, amount(亿元), name
    """
    try:
        import tushare as ts
        token = os.getenv('TUSHARE_TOKEN')
        if not token:
            return pd.DataFrame()
        pro = ts.pro_api(token)

        start = (datetime.strptime(trade_date, '%Y%m%d')
                 - timedelta(days=days + 30)).strftime('%Y%m%d')

        # 拉取历史日线（全市场，按日期逐日聚合）
        # 为减少 API 调用量，直接拉当日 + 近 days 个交易日
        sb = pro.stock_basic(exchange='', list_status='L',
                             fields='ts_code,industry')

        # 获取近期交易日列表
        cal = pro.trade_cal(exchange='SSE', start_date=start, end_date=trade_date)
        open_days = sorted(cal[cal['is_open'] == 1]['cal_date'].tolist())[-days:]

        chunks = []
        for d in open_days:
            try:
                dd = pro.daily(trade_date=d, fields='ts_code,trade_date,close,pct_chg,amount')
                if dd is not None and not dd.empty:
                    dd['amount'] = dd['amount'] / 100000   # 千元→亿元
                    merged = dd.merge(sb, on='ts_code', how='left')
                    merged = merged.dropna(subset=['industry'])
                    agg = merged.groupby('industry').agg(
                        pct_chg=('pct_chg', 'mean'),
                        amount=('amount', 'sum'),
                        close=('close', 'mean'),
                        cnt=('ts_code', 'count'),
                    ).reset_index()
                    agg['trade_date'] = d
                    agg = agg.rename(columns={'industry': 'ts_code'})
                    agg['name'] = agg['ts_code']
                    chunks.append(agg)
            except Exception as e:
                logger.debug(f"Skip {d}: {e}")

        if not chunks:
            return pd.DataFrame()

        result = pd.concat(chunks, ignore_index=True)
        result = result.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
        logger.info(f"Built board data: {result['ts_code'].nunique()} industries × "
                    f"{result['trade_date'].nunique()} days")
        return result

    except Exception as e:
        logger.error(f"fetch_board_daily failed: {e}")
        return pd.DataFrame()


# ─────────────────────────────────────────────
# Board RPS Calculator
# ─────────────────────────────────────────────

class BoardRPSCalculator:
    """
    板块 RPS 计算器。

    与个股 RPS 逻辑一致：
    1. 计算各板块 N 日累计涨幅
    2. 在全部板块间做百分位排名 × 100
    """

    PERIODS = [5, 10, 20]
    WEIGHTS = {5: 0.4, 10: 0.35, 20: 0.25}

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty or 'pct_chg' not in df.columns:
            return df

        df = df.copy().sort_values(['ts_code', 'trade_date'])

        unique_days = df['trade_date'].nunique()

        for period in self.PERIODS:
            if unique_days <= period:
                continue
            ret_col = f'ret_{period}'
            rps_col = f'rps_{period}'
            df[ret_col] = df.groupby('ts_code')['close'].transform(
                lambda x: x.pct_change(periods=period)
            )
            df[rps_col] = (
                df.groupby('trade_date')[ret_col]
                  .rank(pct=True, na_option='keep') * 100
            )
            df.drop(columns=[ret_col], inplace=True)

        # 综合 RPS
        available = [p for p in self.PERIODS if f'rps_{p}' in df.columns]
        if available:
            total_w = sum(self.WEIGHTS[p] for p in available)
            df['rps_combo'] = sum(
                df[f'rps_{p}'] * self.WEIGHTS[p] for p in available
            ) / total_w
            df['rps_combo'] = df['rps_combo'].round(2)

        return df

    def get_latest(self, df: pd.DataFrame, trade_date: str) -> pd.DataFrame:
        """返回指定日期的板块 RPS，按综合 RPS 降序。"""
        latest = df[df['trade_date'] == trade_date].copy()
        if 'rps_combo' in latest.columns:
            latest = latest.sort_values('rps_combo', ascending=False)
        return latest


# ─────────────────────────────────────────────
# Save to DB
# ─────────────────────────────────────────────

def save_board_prices(df: pd.DataFrame, db_path: Path = DB_PATH):
    """保存板块日线到 board_daily_prices 表。"""
    if df.empty:
        return
    conn = sqlite3.connect(str(db_path))
    # 迁移：补充 pct_chg 列
    existing = {row[1] for row in conn.execute("PRAGMA table_info(board_daily_prices)")}
    if 'pct_chg' not in existing:
        conn.execute("ALTER TABLE board_daily_prices ADD COLUMN pct_chg REAL")
        conn.commit()
    for _, row in df.iterrows():
        conn.execute('''
            INSERT OR REPLACE INTO board_daily_prices
            (ts_code, trade_date, close, pct_chg, vol, amount)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (
            row['ts_code'], row['trade_date'],
            row.get('close'), row.get('pct_chg'),
            row.get('vol'), row.get('amount'),
        ))
    conn.commit()
    conn.close()
    logger.info(f"Saved {len(df)} board_daily_prices rows")


# ─────────────────────────────────────────────
# Reporter
# ─────────────────────────────────────────────

class BoardReportSender:
    def __init__(self, bot_token: str = None, chat_ids: List[str] = None):
        self.bot_token = bot_token or os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_ids  = chat_ids or []

    def format_report(self, latest: pd.DataFrame, trade_date: str) -> str:
        lines = [f"[板块RPS日报] {trade_date}", ""]
        lines.append(f"{'排名':<4} {'板块':<8} {'RPS综合':>8} "
                     f"{'RPS5':>7} {'RPS10':>7} {'RPS20':>7} {'涨跌幅':>7}")
        lines.append("-" * 55)
        for i, (_, row) in enumerate(latest.iterrows(), 1):
            name = row.get('name', row['ts_code'])
            combo = f"{row.get('rps_combo', 0):.1f}"
            r5    = f"{row.get('rps_5', 0):.1f}" if 'rps_5' in row else "  -"
            r10   = f"{row.get('rps_10', 0):.1f}" if 'rps_10' in row else "  -"
            r20   = f"{row.get('rps_20', 0):.1f}" if 'rps_20' in row else "  -"
            pct   = f"{row.get('pct_chg', 0):+.2f}%"
            lines.append(f"{i:<4} {name:<8} {combo:>8} {r5:>7} {r10:>7} {r20:>7} {pct:>7}")
        return "\n".join(lines)

    def send(self, message: str):
        if not self.bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN not configured")
            return
        try:
            import requests
            for chat_id in self.chat_ids:
                url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
                requests.post(url, json={'chat_id': chat_id, 'text': message}, timeout=10)
                logger.info(f"Sent to {chat_id}")
        except Exception as e:
            logger.error(f"Send failed: {e}")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Board RPS Report')
    parser.add_argument('--date', type=str, help='Trade date (YYYYMMDD)')
    parser.add_argument('--days', type=int, default=60, help='History days')
    parser.add_argument('--send', action='store_true', help='Send via Telegram')
    args = parser.parse_args()

    trade_date = args.date or datetime.now().strftime('%Y%m%d')

    logger.info(f"Fetching board data for {trade_date}...")
    raw = fetch_board_daily(trade_date, days=args.days)
    if raw.empty:
        logger.error("No board data, abort")
        return

    # 保存原始数据到 DB
    save_board_prices(raw[raw['trade_date'] == trade_date])

    # 计算 RPS
    calc   = BoardRPSCalculator()
    rps_df = calc.calculate(raw)
    latest = calc.get_latest(rps_df, trade_date)

    # 打印
    sender  = BoardReportSender()
    message = sender.format_report(latest, trade_date)
    print("\n" + message + "\n")

    if args.send:
        sender.send(message)


if __name__ == '__main__':
    main()
