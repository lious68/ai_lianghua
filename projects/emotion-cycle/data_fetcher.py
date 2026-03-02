"""
Emotion Cycle Data Fetcher
Fetches 399101.SZ (中小综指, proxy for 880005) OHLC,
limit-up/down counts, and total market amount data.
"""

import os
import sys
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
import pandas as pd

# ── 路径统一从 core.paths 获取 ──
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent.parent))
from core.paths import Paths
from core.logging_cfg import get_logger

logger = get_logger(__name__)

_EC = Paths.EmotionCycle   # 简写


def _get_tushare_pro():
    """Return tushare pro_api instance, or None if unavailable."""
    try:
        import tushare as ts
        from dotenv import load_dotenv
        load_dotenv()
        token = os.getenv('TUSHARE_TOKEN')
        if not token:
            logger.warning("TUSHARE_TOKEN not set")
            return None
        return ts.pro_api(token)
    except ImportError:
        logger.error("tushare not installed")
        return None


class EmotionDataFetcher:
    def __init__(self):
        self.index_code = "399101.SZ"   # 中小综指，880005 标准替代

    # ─────────────────────────────────────────────
    # 1. 指数 OHLC（用于计算 CCI / MA）
    # ─────────────────────────────────────────────

    def fetch_880005_ohlc(self, days: int = 60) -> pd.DataFrame:
        """
        Fetch 中小综指 399101.SZ OHLC as proxy for 880005.
        Tushare index_daily → fallback mock.
        """
        df = self._fetch_index_ohlc_tushare(days)
        if not df.empty:
            return df
        logger.warning("Using mock OHLC data")
        return self._get_default_data(days)

    def _fetch_index_ohlc_tushare(self, days: int) -> pd.DataFrame:
        pro = _get_tushare_pro()
        if pro is None:
            return pd.DataFrame()
        try:
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=days + 60)).strftime('%Y%m%d')
            df = pro.index_daily(ts_code=self.index_code,
                                 start_date=start_date, end_date=end_date)
            if df is None or df.empty:
                return pd.DataFrame()
            df = df.sort_values('trade_date').reset_index(drop=True)
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            # Tushare index_daily: amount 单位是千元，转亿元
            if 'amount' in df.columns:
                df['amount'] = df['amount'] / 100000   # 千元 → 亿元
            logger.info(f"Fetched {len(df)} days of {self.index_code} OHLC")
            return df.tail(days).reset_index(drop=True)
        except Exception as e:
            logger.error(f"Tushare index OHLC fetch failed: {e}")
            return pd.DataFrame()

    def _get_default_data(self, days: int) -> pd.DataFrame:
        import random
        dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
        base = 15000
        data = []
        for d in dates:
            if d.weekday() < 5:
                o = base + random.uniform(-200, 200)
                c = o + random.uniform(-100, 100)
                data.append({
                    'trade_date': d,
                    'open': o,
                    'high': max(o, c) + random.uniform(0, 80),
                    'low': min(o, c) - random.uniform(0, 80),
                    'close': c,
                    'vol': random.uniform(2e8, 5e8),
                    'amount': random.uniform(8000, 15000),  # 亿元
                })
        return pd.DataFrame(data)

    # ─────────────────────────────────────────────
    # 2. 全市场成交额（沪深合计，亿元）
    # ─────────────────────────────────────────────

    def fetch_market_amount(self, trade_date: str) -> float:
        """
        Fetch total A-share market trading amount (沪深合计).
        Tushare daily amount 单位：千元，汇总后 /100000 → 亿元。
        若目标日期数据未入库（收盘后延迟），自动往前找最近一个有数据的交易日。
        """
        pro = _get_tushare_pro()
        if pro is None:
            return 10000.0
        try:
            df = pro.daily(trade_date=trade_date, fields='ts_code,amount')
            if df is not None and not df.empty:
                total_billion = df['amount'].sum() / 100000   # 千元 → 亿元
                logger.info(f"Market amount {trade_date}: {total_billion:.0f} 亿")
                return total_billion

            # 数据未入库，往前最多找 5 个交易日
            logger.warning(f"No daily data for {trade_date} (non-trading day or data not yet available)")
            from datetime import datetime, timedelta
            for delta in range(1, 6):
                prev = (datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=delta)).strftime('%Y%m%d')
                df2 = pro.daily(trade_date=prev, fields='ts_code,amount')
                if df2 is not None and not df2.empty:
                    total_billion = df2['amount'].sum() / 100000
                    logger.info(f"Using previous trading date {prev}: {total_billion:.0f} 亿")
                    return total_billion
            return 0.0
        except Exception as e:
            logger.error(f"Failed to fetch market amount: {e}")
            return 0.0

    # ─────────────────────────────────────────────
    # 3. 涨停 / 跌停数（全市场）
    # ─────────────────────────────────────────────

    def fetch_limit_stats(self, trade_date: str) -> Dict:
        """
        Fetch limit-up and limit-down counts for all A shares.
        Returns dict: {limit_up, limit_down, ld_ratio, limit_up_df}

        涨停判断：pct_chg >= 9.5%（含ST 5% 涨停及科创板/创业板 20% 涨停跳过边界情况，
        业内通常用 >= 9.5% 作为宽口径）
        跌停判断：pct_chg <= -9.5%
        若目标日期数据未入库，自动往前找最近一个有数据的交易日。
        """
        pro = _get_tushare_pro()
        if pro is None:
            return self._mock_limit_stats()
        try:
            df = pro.daily(trade_date=trade_date,
                           fields='ts_code,pct_chg,close,vol,amount')

            # 数据未入库，往前最多找 5 个交易日
            if df is None or df.empty:
                logger.warning(f"No daily data for {trade_date}")
                from datetime import datetime, timedelta
                for delta in range(1, 6):
                    prev = (datetime.strptime(trade_date, '%Y%m%d') - timedelta(days=delta)).strftime('%Y%m%d')
                    df2 = pro.daily(trade_date=prev, fields='ts_code,pct_chg,close,vol,amount')
                    if df2 is not None and not df2.empty:
                        logger.info(f"Using previous trading date {prev} for limit stats")
                        df = df2
                        break
                else:
                    return {'limit_up': 0, 'limit_down': 0,
                            'ld_ratio': 0.0, 'limit_up_df': pd.DataFrame()}

            limit_up_df   = df[df['pct_chg'] >= 9.5].copy()
            limit_down_df = df[df['pct_chg'] <= -9.5].copy()

            lu = len(limit_up_df)
            ld = len(limit_down_df)
            ld_ratio = lu / max(ld, 1)

            logger.info(f"Limit stats {trade_date}: 涨停={lu}, 跌停={ld}, 比={ld_ratio:.2f}")
            return {
                'limit_up':    lu,
                'limit_down':  ld,
                'ld_ratio':    round(ld_ratio, 2),
                'limit_up_df': limit_up_df,
            }
        except Exception as e:
            logger.error(f"Failed to fetch limit stats: {e}")
            return self._mock_limit_stats()

    def _mock_limit_stats(self) -> Dict:
        return {
            'limit_up': 80, 'limit_down': 20,
            'ld_ratio': 4.0, 'limit_up_df': pd.DataFrame()
        }

    # ─────────────────────────────────────────────
    # 保留旧接口兼容（main.py 调用）
    # ─────────────────────────────────────────────

    def fetch_limit_up_stocks(self, trade_date: str) -> pd.DataFrame:
        """Legacy: return limit-up DataFrame only."""
        return self.fetch_limit_stats(trade_date)['limit_up_df']

    # ─────────────────────────────────────────────
    # 4. 历史数据读写
    # ─────────────────────────────────────────────

    def get_emotion_history(self) -> pd.DataFrame:
        history_path = _EC.history
        if history_path.exists():
            df = pd.read_csv(history_path)
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            return df
        return pd.DataFrame()

    def save_emotion_history(self, df: pd.DataFrame):
        """Append/upsert daily summary row to emotion_history.csv"""
        history_path = _EC.history
        history_path.parent.mkdir(parents=True, exist_ok=True)

        df = df.copy()
        df['trade_date'] = df['trade_date'].astype(str)

        if history_path.exists():
            existing = pd.read_csv(history_path)
            df = pd.concat([existing, df], ignore_index=True)
            df = df.drop_duplicates(subset=['trade_date'], keep='last')

        df.to_csv(history_path, index=False)
        logger.info(f"Emotion history saved → {history_path}")

    def save_limit_history(self, df: pd.DataFrame, trade_date: str):
        if df.empty:
            return
        history_path = _EC.limits
        history_path.parent.mkdir(parents=True, exist_ok=True)
        df = df.copy()
        df['trade_date'] = trade_date
        if history_path.exists():
            existing = pd.read_csv(history_path)
            df = pd.concat([existing, df], ignore_index=True)
        df.to_csv(history_path, index=False)
        logger.info(f"Limit history saved → {history_path}")


if __name__ == '__main__':
    import logging
    logging.basicConfig(level=logging.INFO)
    fetcher = EmotionDataFetcher()
    trade_date = datetime.now().strftime('%Y%m%d')

    print("=== OHLC ===")
    ohlc = fetcher.fetch_880005_ohlc()
    print(ohlc.tail(3).to_string())

    print("\n=== Market Amount ===")
    amt = fetcher.fetch_market_amount(trade_date)
    print(f"{amt:.0f} 亿")

    print("\n=== Limit Stats ===")
    stats = fetcher.fetch_limit_stats(trade_date)
    print(f"涨停={stats['limit_up']}, 跌停={stats['limit_down']}, 比={stats['ld_ratio']}")
