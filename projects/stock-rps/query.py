#!/usr/bin/env python3
"""
RPS Query Tool
从本地 rps_daily 数据库直接查询，不拉取任何远程数据。

用法：
  python query.py                        # 查最近一天，Top50，RPS>=80
  python query.py --date 20260302        # 指定日期
  python query.py --top 20 --min 90      # Top20，RPS>=90
  python query.py --dates                # 列出数据库中所有已有日期
  python query.py --trend 688308.SH      # 查某只股票的 RPS 历史趋势
"""

import sys
import sqlite3
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from core.paths import Paths
from core.logging_cfg import setup_logging, get_logger

setup_logging(project="stock-rps")
logger = get_logger(__name__)

DB_PATH = Paths.StockRps.db

HEADER_MAP = {
    'ts_code':   '代码',
    'name':      '名称',
    'industry':  '行业',
    'rps_combo': '综合RPS',
    'rps_10':    'RPS10',
    'rps_20':    'RPS20',
    'rps_50':    'RPS50',
    'rps_120':   'RPS120',
    'close':     '收盘价',
    'pct_chg':   '涨跌%',
}


def get_connection():
    if not DB_PATH.exists():
        logger.error(f"DB not found: {DB_PATH}，请先运行 main_update.py")
        sys.exit(1)
    return sqlite3.connect(str(DB_PATH))


def list_dates():
    """列出数据库中所有已有交易日。"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT trade_date, COUNT(*) as cnt FROM rps_daily GROUP BY trade_date ORDER BY trade_date DESC"
    ).fetchall()
    conn.close()
    print(f"\n{'日期':<12} {'股票数':>6}")
    print('-' * 20)
    for trade_date, cnt in rows:
        print(f"{trade_date:<12} {cnt:>6}")
    print(f"\n共 {len(rows)} 个交易日\n")


def get_latest_date() -> str:
    """从 DB 取最近一个有数据的交易日。"""
    conn = get_connection()
    row = conn.execute(
        "SELECT MAX(trade_date) FROM rps_daily"
    ).fetchone()
    conn.close()
    if not row or not row[0]:
        logger.error("rps_daily 表为空，请先运行 main_update.py")
        sys.exit(1)
    return row[0]


def query_top(trade_date: str, top_n: int = 50, min_rps: float = 80.0):
    """查询某日 RPS Top N。"""
    conn = get_connection()
    import pandas as pd
    df = pd.read_sql_query('''
        SELECT r.trade_date, r.ts_code, s.name, s.industry,
               r.rps_combo, r.rps_10, r.rps_20, r.rps_50, r.rps_120,
               r.close, r.pct_chg
        FROM rps_daily r
        LEFT JOIN stock_basic s ON r.ts_code = s.ts_code
        WHERE r.trade_date = ?
          AND r.rps_combo >= ?
        ORDER BY r.rps_combo DESC
        LIMIT ?
    ''', conn, params=(trade_date, min_rps, top_n))
    conn.close()

    print(f"\n{'='*72}")
    print(f"  RPS Top {top_n} — {trade_date}  (RPS_combo >= {min_rps})")
    print(f"{'='*72}")

    if df.empty:
        print(f"  无符合条件的股票")
    else:
        cols = ['ts_code', 'name', 'rps_combo', 'rps_10', 'rps_20',
                'rps_50', 'rps_120', 'close', 'pct_chg']
        cols = [c for c in cols if c in df.columns]
        display = df[cols].copy()
        display['name'] = display['name'].fillna('--')
        display.columns = [HEADER_MAP.get(c, c) for c in cols]
        print(display.to_string(index=False, float_format=lambda x: f"{x:6.1f}"))

    print(f"{'='*72}")
    print(f"  共 {len(df)} 只  |  DB: {DB_PATH}\n")


def query_trend(ts_code: str, days: int = 30):
    """查询某只股票最近 N 天的 RPS 历史趋势。"""
    conn = get_connection()
    import pandas as pd
    df = pd.read_sql_query('''
        SELECT r.trade_date, r.rps_combo, r.rps_10, r.rps_20,
               r.rps_50, r.rps_120, r.close, r.pct_chg,
               s.name
        FROM rps_daily r
        LEFT JOIN stock_basic s ON r.ts_code = s.ts_code
        WHERE r.ts_code = ?
        ORDER BY r.trade_date DESC
        LIMIT ?
    ''', conn, params=(ts_code, days))
    conn.close()

    if df.empty:
        print(f"\n  {ts_code} 无数据，请先运行 main_update.py")
        return

    name = df['name'].iloc[0] or '--'
    print(f"\n{'='*65}")
    print(f"  {ts_code}  {name}  — 最近 {len(df)} 天 RPS 趋势")
    print(f"{'='*65}")
    cols = ['trade_date', 'rps_combo', 'rps_10', 'rps_20',
            'rps_50', 'rps_120', 'close', 'pct_chg']
    display = df[cols].copy()
    display.columns = ['日期', '综合RPS', 'RPS10', 'RPS20', 'RPS50', 'RPS120', '收盘价', '涨跌%']
    print(display.to_string(index=False, float_format=lambda x: f"{x:6.1f}"))
    print(f"{'='*65}\n")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='RPS 本地查询（不拉远程数据）')
    parser.add_argument('--date',  type=str, help='交易日 YYYYMMDD，默认取 DB 最新日期')
    parser.add_argument('--top',   type=int, default=50, help='Top N（默认 50）')
    parser.add_argument('--min',   type=float, default=80.0, help='最低 RPS_combo（默认 80）')
    parser.add_argument('--dates', action='store_true', help='列出 DB 中所有已有交易日')
    parser.add_argument('--trend', type=str, metavar='TS_CODE', help='查某只股票 RPS 历史趋势')
    parser.add_argument('--days',  type=int, default=30, help='趋势查询天数（默认 30）')
    args = parser.parse_args()

    if args.dates:
        list_dates()
        return

    if args.trend:
        query_trend(args.trend, days=args.days)
        return

    trade_date = args.date or get_latest_date()
    query_top(trade_date, top_n=args.top, min_rps=args.min)


if __name__ == '__main__':
    main()
