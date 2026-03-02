"""
Amount Ranking Module
Track top 500 stocks by trading amount (成交额), daily incremental update.

注意：Tushare pro.daily() 返回的 amount 单位为千元（元/1000），
存入 DB 前统一转换为亿元（/ 100000）。
"""

import os
import sys
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import List, Dict
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv()

from core.paths import Paths
from core.logging_cfg import get_logger

logger = get_logger(__name__)

DB_PATH = Paths.StockRps.db


class AmountRankingUpdater:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = str(db_path)

    def fetch_daily_amount(self, trade_date: str, top_n: int = 500) -> pd.DataFrame:
        """
        从 Tushare 拉取全市场日线，按成交额取 Top N。
        amount 单位：千元 → 亿元（/ 100000）
        """
        try:
            import tushare as ts
            token = os.getenv('TUSHARE_TOKEN')
            if not token:
                logger.warning("TUSHARE_TOKEN not set")
                return pd.DataFrame()

            pro = ts.pro_api(token)
            df = pro.daily(trade_date=trade_date,
                           fields='ts_code,trade_date,close,vol,amount,pct_chg')
            if df is None or df.empty:
                logger.warning(f"No data for {trade_date}")
                return pd.DataFrame()

            # 单位转换：千元 → 亿元
            df['amount'] = df['amount'] / 100000
            df = df.sort_values('amount', ascending=False).head(top_n).copy()
            df['rank'] = range(1, len(df) + 1)
            df['trade_date'] = df['trade_date'].astype(str)
            logger.info(f"Fetched {len(df)} amount-ranked stocks for {trade_date}")
            return df

        except Exception as e:
            logger.error(f"fetch_daily_amount failed: {e}")
            return pd.DataFrame()

    def save(self, df: pd.DataFrame, trade_date: str):
        if df.empty:
            return
        conn = sqlite3.connect(self.db_path)
        # 先删当日旧数据，保证幂等
        conn.execute('DELETE FROM amount_ranking WHERE trade_date = ?', (trade_date,))
        for _, row in df.iterrows():
            conn.execute('''
                INSERT INTO amount_ranking
                (trade_date, rank, ts_code, amount, vol, close, pct_chg)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (
                trade_date, int(row['rank']), row['ts_code'],
                row.get('amount'), row.get('vol'),
                row.get('close'), row.get('pct_chg'),
            ))
        conn.commit()
        conn.close()
        logger.info(f"Saved {len(df)} amount_ranking rows for {trade_date}")

    def get_top(self, trade_date: str, top_n: int = 20) -> pd.DataFrame:
        conn = sqlite3.connect(self.db_path)
        df = pd.read_sql_query('''
            SELECT * FROM amount_ranking
            WHERE trade_date = ?
            ORDER BY rank
            LIMIT ?
        ''', conn, params=(trade_date, top_n))
        conn.close()
        return df


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Amount Ranking Update')
    parser.add_argument('--date',  type=str, help='Trade date (YYYYMMDD)')
    parser.add_argument('--top',   type=int, default=500, help='Top N stocks')
    parser.add_argument('--print', type=int, default=20, dest='show',
                        help='Print top N after save')
    args = parser.parse_args()

    trade_date = args.date or datetime.now().strftime('%Y%m%d')

    updater = AmountRankingUpdater()
    df = updater.fetch_daily_amount(trade_date, top_n=args.top)
    if not df.empty:
        updater.save(df, trade_date)
        top = updater.get_top(trade_date, top_n=args.show)
        print(f"\n成交额 Top {args.show} — {trade_date}")
        print(top[['rank', 'ts_code', 'amount', 'close', 'pct_chg']].to_string(index=False))
    else:
        logger.warning("No data to save")


if __name__ == '__main__':
    main()
