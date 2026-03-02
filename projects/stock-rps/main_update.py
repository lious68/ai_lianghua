#!/usr/bin/env python3
"""
RPS (Relative Performance Strength) Ranking System
Main entry point for daily RPS data updates

RPS 计算方式（业内标准，参考 Minervini / 欧奈尔）：
  对每只股票计算 N 日累计涨幅百分比，然后在全体股票中做百分位排名 × 100
  结果 0~100，越高越强。
  常用周期：10/20/50/120 日（对应约2周/1月/季/半年）

综合 RPS = 0.4×RPS_10 + 0.2×RPS_20 + 0.2×RPS_50 + 0.2×RPS_120
"""

import os
import sys
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
import pandas as pd
import numpy as np

# ── core 路径注入 ──
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()

from core.paths import Paths
from core.logging_cfg import setup_logging, get_logger

setup_logging(project="stock-rps")
logger = get_logger(__name__)

try:
    import tushare as ts
except ImportError:
    logger.warning("tushare not installed")
    ts = None

DB_PATH = Paths.StockRps.db


# ─────────────────────────────────────────────
# Database
# ─────────────────────────────────────────────

class RPSDatabase:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = str(db_path)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_database()
        self._migrate()

    def _init_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rps_daily (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date TEXT NOT NULL,
                ts_code    TEXT NOT NULL,
                rps_10     REAL,
                rps_20     REAL,
                rps_50     REAL,
                rps_120    REAL,
                rps_combo  REAL,
                close      REAL,
                pct_chg    REAL,
                UNIQUE(trade_date, ts_code)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS amount_ranking (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date TEXT NOT NULL,
                rank       INTEGER NOT NULL,
                ts_code    TEXT NOT NULL,
                amount     REAL,
                vol        REAL,
                close      REAL,
                pct_chg    REAL,
                UNIQUE(trade_date, ts_code)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS board_daily_prices (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_code    TEXT NOT NULL,
                trade_date TEXT NOT NULL,
                close      REAL,
                pct_chg    REAL,
                vol        REAL,
                amount     REAL,
                UNIQUE(ts_code, trade_date)
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stock_basic (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_code   TEXT UNIQUE NOT NULL,
                name      TEXT,
                industry  TEXT,
                list_date TEXT
            )
        ''')

        conn.commit()
        conn.close()
        logger.info("DB initialized")

    def _migrate(self):
        """Add new columns if upgrading from old schema."""
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        existing = {row[1] for row in cur.execute("PRAGMA table_info(rps_daily)")}
        for col, typ in [('rps_combo', 'REAL'), ('pct_chg', 'REAL')]:
            if col not in existing:
                cur.execute(f"ALTER TABLE rps_daily ADD COLUMN {col} {typ}")
                logger.info(f"Migrated rps_daily: added column {col}")
        conn.commit()
        conn.close()

    def get_connection(self):
        return sqlite3.connect(self.db_path)

    def fetch_df(self, query: str, params: tuple = ()) -> pd.DataFrame:
        conn = self.get_connection()
        df = pd.read_sql_query(query, conn, params=params)
        conn.close()
        return df


# ─────────────────────────────────────────────
# RPS Calculator
# ─────────────────────────────────────────────

class RPSCalculator:
    """
    计算 RPS（相对强弱排名）。

    步骤：
    1. 对每只股票计算 N 日累计涨幅（pct_change(N)）
    2. 在相同 trade_date 的所有股票中做百分位排名 × 100
    3. 综合 RPS = 加权平均（0.4×10d + 0.2×20d + 0.2×50d + 0.2×120d）
    """

    PERIODS = [10, 20, 50, 120]
    WEIGHTS = {10: 0.4, 20: 0.2, 50: 0.2, 120: 0.2}

    def __init__(self, db: RPSDatabase):
        self.db = db

    def calculate_rps(self, prices_df: pd.DataFrame) -> pd.DataFrame:
        if prices_df.empty or 'close' not in prices_df.columns:
            return prices_df

        df = prices_df.copy()
        df['trade_date'] = df['trade_date'].astype(str)
        df = df.sort_values(['ts_code', 'trade_date'])

        unique_days = df['trade_date'].nunique()
        logger.info(f"Calculating RPS: {df['ts_code'].nunique()} stocks × {unique_days} days")

        # Step 1: N-日累计涨幅
        for period in self.PERIODS:
            if unique_days <= period:
                logger.warning(f"Skipping RPS_{period}: need {period+1} days, have {unique_days}")
                continue
            col = f'ret_{period}'
            df[col] = df.groupby('ts_code')['close'].transform(
                lambda x: x.pct_change(periods=period)
            )

        # Step 2: 每个 trade_date 内做百分位排名
        for period in self.PERIODS:
            ret_col = f'ret_{period}'
            rps_col = f'rps_{period}'
            if ret_col not in df.columns:
                continue
            df[rps_col] = (
                df.groupby('trade_date')[ret_col]
                  .rank(pct=True, na_option='keep') * 100
            )
            df.drop(columns=[ret_col], inplace=True)

        # Step 3: 综合 RPS（加权平均已有周期）
        available = [p for p in self.PERIODS if f'rps_{p}' in df.columns]
        if available:
            total_w = sum(self.WEIGHTS[p] for p in available)
            df['rps_combo'] = sum(
                df[f'rps_{p}'] * self.WEIGHTS[p] for p in available
            ) / total_w
            df['rps_combo'] = df['rps_combo'].round(2)

        return df

    def save_rps(self, rps_df: pd.DataFrame, trade_date: str):
        """只保存目标 trade_date 的记录。"""
        target = rps_df[rps_df['trade_date'] == trade_date]
        if target.empty:
            logger.warning(f"No RPS rows for {trade_date}")
            return

        conn = self.db.get_connection()
        cursor = conn.cursor()
        saved = 0
        for _, row in target.iterrows():
            cursor.execute('''
                INSERT OR REPLACE INTO rps_daily
                (trade_date, ts_code, rps_10, rps_20, rps_50, rps_120, rps_combo, close, pct_chg)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                str(row['trade_date']),
                row['ts_code'],
                _safe(row, 'rps_10'),
                _safe(row, 'rps_20'),
                _safe(row, 'rps_50'),
                _safe(row, 'rps_120'),
                _safe(row, 'rps_combo'),
                _safe(row, 'close'),
                _safe(row, 'pct_chg'),
            ))
            saved += 1

        conn.commit()
        conn.close()
        logger.info(f"Saved {saved} RPS records for {trade_date}")

    def get_top_rps(self, trade_date: str, top_n: int = 50,
                    min_rps: float = 80.0) -> pd.DataFrame:
        """查询某日 RPS 排名靠前的股票。"""
        return self.db.fetch_df('''
            SELECT r.*, s.name, s.industry
            FROM rps_daily r
            LEFT JOIN stock_basic s ON r.ts_code = s.ts_code
            WHERE r.trade_date = ?
              AND r.rps_combo >= ?
            ORDER BY r.rps_combo DESC
            LIMIT ?
        ''', (trade_date, min_rps, top_n))


# ─────────────────────────────────────────────
# Data Fetching
# ─────────────────────────────────────────────

def _safe(row, col):
    v = row.get(col)
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return float(v)


def _get_pro():
    token = os.getenv('TUSHARE_TOKEN')
    if not token or ts is None:
        raise RuntimeError("TUSHARE_TOKEN not configured or tushare not installed")
    return ts.pro_api(token)


def get_last_trading_date(before: str = None) -> str:
    """
    返回 before 日期（含）当天或之前最近一个交易日。
    - 如果 before 本身是交易日，直接返回
    - 否则往前找，最多查 15 天（覆盖春节等长假）
    """
    before = before or datetime.now().strftime('%Y%m%d')
    pro = _get_pro()
    start = (datetime.strptime(before, '%Y%m%d') - timedelta(days=15)).strftime('%Y%m%d')
    cal = pro.trade_cal(exchange='SSE', start_date=start, end_date=before)
    open_days = sorted(cal[cal['is_open'] == 1]['cal_date'].tolist())
    if not open_days:
        return before
    result = open_days[-1]
    if result != before:
        logger.info(f"{before} 非交易日，使用最近交易日 {result}")
    return result


def fetch_stock_list(market: str = '科创板') -> List[str]:
    """获取股票代码列表。market: '科创板' | 'all'"""
    pro = _get_pro()
    df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name')
    if market == '科创板':
        return df[df['ts_code'].str.startswith('688')]['ts_code'].tolist()
    return df['ts_code'].tolist()


def fetch_daily_prices(stock_list: List[str], start_date: str,
                       end_date: str) -> pd.DataFrame:
    """
    批量拉取日线数据。
    返回 DataFrame 含列：ts_code, trade_date(str), open, high, low, close,
                          vol, amount(亿元), pct_chg
    """
    pro = _get_pro()
    chunks = []
    total = len(stock_list)

    for i, code in enumerate(stock_list):
        try:
            df = pro.daily(ts_code=code, start_date=start_date, end_date=end_date,
                           fields='ts_code,trade_date,open,high,low,close,vol,amount,pct_chg')
            if df is not None and not df.empty:
                chunks.append(df)
        except Exception as e:
            logger.debug(f"Skip {code}: {e}")

        if (i + 1) % 100 == 0:
            logger.info(f"  fetched {i+1}/{total}...")

    if not chunks:
        return pd.DataFrame()

    result = pd.concat(chunks, ignore_index=True)
    result['trade_date'] = result['trade_date'].astype(str)
    # amount: Tushare daily 单位千元 → 亿元
    result['amount'] = result['amount'] / 100000
    result = result.sort_values(['ts_code', 'trade_date']).reset_index(drop=True)
    logger.info(f"Fetched {len(result)} rows, {result['ts_code'].nunique()} stocks")
    return result


def fetch_stock_basic(db: RPSDatabase):
    """拉取并缓存股票基本信息到 stock_basic 表。"""
    pro = _get_pro()
    df = pro.stock_basic(exchange='', list_status='L',
                         fields='ts_code,name,industry,list_date')
    if df.empty:
        return
    conn = db.get_connection()
    df.to_sql('stock_basic', conn, if_exists='replace', index=False)
    conn.close()
    logger.info(f"Saved {len(df)} stock_basic records")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def send_telegram(message: str):
    """通过 Telegram Bot 推送消息，读取环境变量 TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_IDS。"""
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    raw   = os.getenv('TELEGRAM_CHAT_IDS', '')
    chat_ids = [c.strip() for c in raw.split(',') if c.strip()]
    if not token or not chat_ids:
        logger.warning("Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_IDS missing)")
        return
    try:
        import requests
        for chat_id in chat_ids:
            url  = f"https://api.telegram.org/bot{token}/sendMessage"
            resp = requests.post(url, json={
                'chat_id':    chat_id,
                'text':       message,
                'parse_mode': 'Markdown',
            }, timeout=15)
            if resp.status_code == 200:
                logger.info(f"RPS report sent to {chat_id}")
            else:
                logger.error(f"Telegram send failed: {resp.text}")
    except Exception as e:
        logger.error(f"Telegram send exception: {e}")


def format_rps_message(top: pd.DataFrame, trade_date: str, market: str) -> str:
    """将 Top RPS 结果格式化为 Telegram 消息（纯文本，避免 Markdown 转义问题）。"""
    lines = [
        f"📊 RPS 排行榜 — {trade_date}（{market}）",
        f"RPS_combo >= 80，共 {len(top)} 只",
        "",
    ]
    if top.empty:
        lines.append("暂无符合条件的股票")
    else:
        cols = ['ts_code', 'name', 'rps_combo', 'rps_10', 'rps_20', 'rps_50', 'rps_120', 'pct_chg']
        cols = [c for c in cols if c in top.columns]
        for _, row in top.head(30).iterrows():   # TG 消息有长度限制，最多发 30 条
            name     = str(row.get('name', ''))[:6]
            combo    = f"{row.get('rps_combo', 0):.1f}"
            pct      = f"{row.get('pct_chg', 0):+.2f}%" if 'pct_chg' in row else ''
            lines.append(f"{row['ts_code']}  {name:<6}  RPS={combo}  {pct}")
    return "\n".join(lines)


def main():
    import argparse

    parser = argparse.ArgumentParser(description='RPS Data Update')
    parser.add_argument('--date',   type=str, help='Target trade date (YYYYMMDD)')
    parser.add_argument('--days',   type=int, default=130,
                        help='Historical days to fetch for RPS calculation (default 130)')
    parser.add_argument('--market', type=str, default='科创板',
                        help='科创板 | all')
    parser.add_argument('--top',    type=int, default=50,
                        help='Print top N stocks by RPS_combo')
    parser.add_argument('--basic',  action='store_true',
                        help='Refresh stock_basic table')
    parser.add_argument('--send',   action='store_true',
                        help='Send report via Telegram')
    args = parser.parse_args()

    db = RPSDatabase()
    calculator = RPSCalculator(db)

    # 确定目标交易日
    try:
        trade_date = args.date or get_last_trading_date()
    except Exception as e:
        logger.error(f"Cannot get trading date: {e}")
        return
    logger.info(f"Target trade date: {trade_date}")

    # 可选：刷新股票基本信息
    if args.basic:
        fetch_stock_basic(db)

    # 拉取股票列表
    try:
        stock_list = fetch_stock_list(args.market)
    except Exception as e:
        logger.error(f"Cannot fetch stock list: {e}")
        return
    logger.info(f"Stock list: {len(stock_list)} ({args.market})")

    # 确定历史起始日期（多拉一些保证 rps_120 有足够数据）
    start_dt = (datetime.strptime(trade_date, '%Y%m%d')
                - timedelta(days=args.days + 60)).strftime('%Y%m%d')

    # 拉取日线数据
    logger.info(f"Fetching daily prices {start_dt} → {trade_date}...")
    prices = fetch_daily_prices(stock_list, start_dt, trade_date)
    if prices.empty:
        logger.error("No price data fetched, abort")
        return

    # 计算 RPS
    logger.info("Calculating RPS...")
    rps_df = calculator.calculate_rps(prices)

    # 保存
    calculator.save_rps(rps_df, trade_date)

    # 打印 Top N
    top = calculator.get_top_rps(trade_date, top_n=args.top, min_rps=80)
    print(f"\n{'='*65}")
    print(f"  RPS Top {args.top} — {trade_date}  ({args.market})")
    print(f"{'='*65}")
    if top.empty:
        print("  No results (RPS_combo >= 80)")
    else:
        cols = ['ts_code', 'name', 'rps_combo', 'rps_10', 'rps_20',
                'rps_50', 'rps_120', 'close', 'pct_chg']
        cols = [c for c in cols if c in top.columns]
        print(top[cols].to_string(index=False, float_format=lambda x: f"{x:6.1f}"))
    print(f"{'='*65}\n")
    print(f"  DB: {DB_PATH}\n")

    # TG 推送
    if args.send:
        msg = format_rps_message(top, trade_date, args.market)
        send_telegram(msg)


if __name__ == '__main__':
    main()
