"""
VCP Scanner - Volatility Contraction Pattern Scanner

VCP 标准定义（Mark Minervini）:
1. 股价在 52 周高点附近（距高点不超过 30%）
2. 出现 2-4 次波动收缩（每次高点和低点都比前一次小）
3. 成交量逐步萎缩
4. 最后一次收缩幅度最小（< 15%）
5. 均线多头排列（MA50 > MA150 > MA200，或至少 MA10 > MA20 > MA50）
"""

import os
import sys
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import pandas as pd
import numpy as np
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from core.paths import Paths
from core.logging_cfg import setup_logging, get_logger

setup_logging(project="vcp-scanner")
logger = get_logger(__name__)

DB_PATH = Paths.VcpScanner.db


def init_db():
    """Initialize SQLite database"""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS vcp_results (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_date   TEXT NOT NULL,
            ts_code     TEXT NOT NULL,
            trade_date  TEXT NOT NULL,
            close       REAL,
            dist_from_high  REAL,
            contraction_pct REAL,
            tightness   REAL,
            vol_shrinking   INTEGER,
            ma10        REAL,
            ma20        REAL,
            ma50        REAL,
            score       REAL,
            UNIQUE(scan_date, ts_code)
        )
    ''')
    conn.commit()
    conn.close()


def save_results(results: List[Dict], scan_date: str = None):
    """Save VCP results to database"""
    if not results:
        return
    
    scan_date = scan_date or datetime.now().strftime('%Y%m%d')
    
    init_db()
    conn = sqlite3.connect(str(DB_PATH))
    
    for r in results:
        conn.execute('''
            INSERT OR REPLACE INTO vcp_results
            (scan_date, ts_code, trade_date, close, dist_from_high,
             contraction_pct, tightness, vol_shrinking, ma10, ma20, ma50, score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            scan_date,
            r['ts_code'],
            r['date'],
            r['close'],
            r['dist_from_high'],
            r['contraction_pct'],
            r['tightness'],
            1 if r['vol_shrinking'] else 0,
            r['ma10'],
            r['ma20'],
            r['ma50'],
            r['score']
        ))
    
    conn.commit()
    conn.close()
    logger.info(f"Saved {len(results)} VCP results to {DB_PATH}")


def get_kc_stocks() -> List[str]:
    """Get 科创板 stock list (688xxx)"""
    try:
        import tushare as ts
        token = os.getenv('TUSHARE_TOKEN')
        pro = ts.pro_api(token)
        df = pro.stock_basic(exchange='SSE', list_status='L', fields='ts_code,name')
        kc = df[df['ts_code'].str.startswith('688')]
        logger.info(f"Found {len(kc)} 科创板 stocks")
        return kc['ts_code'].tolist()
    except Exception as e:
        logger.error(f"Failed to get stock list: {e}")
        return []


def fetch_prices(ts_code: str, days: int = 300) -> pd.DataFrame:
    """Fetch price data for a single stock"""
    try:
        import tushare as ts
        token = os.getenv('TUSHARE_TOKEN')
        pro = ts.pro_api(token)
        
        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=days + 60)).strftime('%Y%m%d')
        
        df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
        
        if df is not None and not df.empty:
            df = df.sort_values('trade_date').reset_index(drop=True)
            return df.tail(days)
        
        return pd.DataFrame()
        
    except Exception as e:
        logger.debug(f"Failed {ts_code}: {e}")
        return pd.DataFrame()


def calculate_mas(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate moving averages"""
    df = df.copy()
    for p in [10, 20, 50, 150, 200]:
        if len(df) >= p:
            df[f'ma{p}'] = df['close'].rolling(p).mean()
        else:
            df[f'ma{p}'] = np.nan
    return df


def find_pivots(prices: pd.Series, window: int = 5) -> Tuple[List[int], List[int]]:
    """Find local highs and lows"""
    highs, lows = [], []
    
    for i in range(window, len(prices) - window):
        segment = prices[i - window: i + window + 1]
        if prices[i] == segment.max():
            highs.append(i)
        if prices[i] == segment.min():
            lows.append(i)
    
    return highs, lows


def detect_vcp(df: pd.DataFrame, ts_code: str = '') -> Optional[Dict]:
    """
    Detect VCP pattern
    
    Returns dict with VCP info or None if no pattern found
    """
    if len(df) < 50:
        return None
    
    df = calculate_mas(df)
    
    close = df['close']
    high = df['high']
    low = df['low']
    vol = df['vol']
    
    # ── 条件1: 距 52 周高点不超过 30% ──
    high_52w = high.tail(252).max() if len(df) >= 252 else high.max()
    current_close = close.iloc[-1]
    dist_from_high = (high_52w - current_close) / high_52w
    
    if dist_from_high > 0.30:
        return None  # 离高点太远
    
    # ── 条件2: 均线多头排列（至少 MA10 > MA20 > MA50）──
    ma10 = df['ma10'].iloc[-1]
    ma20 = df['ma20'].iloc[-1]
    ma50 = df['ma50'].iloc[-1]
    
    if pd.isna(ma10) or pd.isna(ma20) or pd.isna(ma50):
        return None
    
    if not (ma10 > ma20 > ma50):
        return None  # 均线未多头排列
    
    # ── 条件3: 识别收缩波段 ──
    # 取最近 60 根 K 线做波段分析
    recent = df.tail(60).reset_index(drop=True)
    recent_high = recent['high']
    recent_low = recent['low']
    recent_vol = recent['vol']
    
    # 找波段高低点
    pivot_highs, pivot_lows = find_pivots(recent_high, window=4)
    
    if len(pivot_highs) < 2:
        return None  # 高点不够，无法判断收缩
    
    # 取最近 3 个高点
    last_highs = [recent_high.iloc[i] for i in pivot_highs[-3:]]
    
    # 高点应该逐步降低（收缩）
    if len(last_highs) >= 2:
        contracting = all(last_highs[i] > last_highs[i + 1] for i in range(len(last_highs) - 1))
        if not contracting:
            return None  # 高点未收缩
    
    # 取最近 3 个低点
    if len(pivot_lows) >= 2:
        last_lows = [recent_low.iloc[i] for i in pivot_lows[-3:]]
        lows_contracting = all(last_lows[i] < last_lows[i + 1] for i in range(len(last_lows) - 1))
        if not lows_contracting:
            return None  # 低点未抬升
    
    # ── 条件4: 计算最后收缩幅度 ──
    if len(pivot_highs) >= 1 and len(pivot_lows) >= 1:
        last_high_idx = pivot_highs[-1]
        # 找该高点之后的最低点
        after_high = recent_low.iloc[last_high_idx:]
        if len(after_high) == 0:
            return None
        
        last_swing_low = after_high.min()
        last_swing_high = recent_high.iloc[last_high_idx]
        
        contraction_pct = (last_swing_high - last_swing_low) / last_swing_high
        
        if contraction_pct > 0.25:
            return None  # 最后收缩幅度超过 25%，太大
    else:
        contraction_pct = 0
    
    # ── 条件5: 成交量萎缩 ──
    recent_30_vol = recent_vol.tail(30)
    first_half_vol = recent_30_vol.iloc[:15].mean()
    second_half_vol = recent_30_vol.iloc[15:].mean()
    
    vol_shrinking = second_half_vol < first_half_vol
    
    # ── 计算紧缩程度（越小越好）──
    # 用最近 10 根 K 线的平均振幅
    recent_10 = df.tail(10)
    avg_range = ((recent_10['high'] - recent_10['low']) / recent_10['close']).mean() * 100
    
    # 与近 60 日平均振幅对比
    avg_range_60 = ((df.tail(60)['high'] - df.tail(60)['low']) / df.tail(60)['close']).mean() * 100
    tightness = 1 - (avg_range / avg_range_60) if avg_range_60 > 0 else 0
    
    # ── 综合评分 ──
    score = 0
    score += tightness * 40           # 收缩紧致度（最高 40 分）
    score += (1 - dist_from_high) * 30  # 距高点近度（最高 30 分）
    score += (1 - contraction_pct) * 20 # 收缩幅度小（最高 20 分）
    score += (10 if vol_shrinking else 0)  # 量能萎缩（10 分）
    
    if score < 30:
        return None
    
    return {
        'ts_code': ts_code,
        'date': df['trade_date'].iloc[-1],
        'close': round(current_close, 2),
        'dist_from_high': round(dist_from_high * 100, 1),  # %
        'contraction_pct': round(contraction_pct * 100, 1),  # %
        'avg_range_pct': round(avg_range, 2),  # %
        'tightness': round(tightness * 100, 1),  # %
        'vol_shrinking': vol_shrinking,
        'ma10': round(ma10, 2),
        'ma20': round(ma20, 2),
        'ma50': round(ma50, 2),
        'score': round(score, 1)
    }


def scan_kc_stocks(top_n: int = 20) -> List[Dict]:
    """Scan all 科创板 stocks for VCP"""
    stocks = get_kc_stocks()
    
    if not stocks:
        logger.error("No stocks found")
        return []
    
    results = []
    total = len(stocks)
    
    for i, ts_code in enumerate(stocks):
        df = fetch_prices(ts_code, days=300)
        
        if df.empty:
            continue
        
        vcp = detect_vcp(df, ts_code)
        
        if vcp:
            results.append(vcp)
        
        if (i + 1) % 100 == 0:
            logger.info(f"Progress: {i+1}/{total}, found {len(results)} VCP patterns")
    
    logger.info(f"Scan complete: {total} stocks, {len(results)} VCP patterns found")
    
    return sorted(results, key=lambda x: x['score'], reverse=True)[:top_n]


def print_results(results: List[Dict]):
    """Print VCP scan results"""
    if not results:
        print("No VCP patterns found")
        return
    
    print(f"\n{'='*70}")
    print(f"VCP Scan Results (KeChuang Ban / STAR Market)")
    print(f"{'='*70}")
    print(f"{'Code':<12} {'Close':>7} {'DstHigh':>8} {'Contrac':>8} {'Tight':>7} {'VolShrk':>8} {'Score':>6}")
    print(f"{'-'*70}")
    
    for r in results:
        vol_flag = 'Y' if r['vol_shrinking'] else 'N'
        print(
            f"{r['ts_code']:<12} "
            f"{r['close']:>7.2f} "
            f"{r['dist_from_high']:>7.1f}% "
            f"{r['contraction_pct']:>7.1f}% "
            f"{r['tightness']:>6.1f}% "
            f"{vol_flag:>8} "
            f"{r['score']:>6.1f}"
        )
    
    print(f"{'='*70}")
    print(f"Total: {len(results)} VCP patterns found")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='VCP Scanner for STAR Market')
    parser.add_argument('--top', type=int, default=20, help='Top N results')
    parser.add_argument('--code', type=str, help='Scan specific stock')
    parser.add_argument('--query', type=str, help='Query results by date (YYYYMMDD), "latest" for most recent')
    args = parser.parse_args()

    # ── Query mode ──
    if args.query:
        init_db()
        conn = sqlite3.connect(str(DB_PATH))
        
        if args.query == 'latest':
            scan_date = conn.execute(
                'SELECT MAX(scan_date) FROM vcp_results'
            ).fetchone()[0]
        else:
            scan_date = args.query
        
        if not scan_date:
            print("No data found in database")
            conn.close()
            return
        
        rows = conn.execute('''
            SELECT ts_code, trade_date, close, dist_from_high,
                   contraction_pct, tightness, vol_shrinking, score
            FROM vcp_results
            WHERE scan_date = ?
            ORDER BY score DESC
        ''', (scan_date,)).fetchall()
        conn.close()
        
        print(f"\nVCP Results for scan_date={scan_date}, {len(rows)} records")
        print(f"{'='*70}")
        print(f"{'Code':<12} {'Close':>7} {'DstHigh':>8} {'Contrac':>8} {'Tight':>7} {'VolShrk':>8} {'Score':>6}")
        print(f"{'-'*70}")
        for row in rows:
            ts_code, trade_date, close, dist, contrac, tight, vol_shrk, score = row
            print(
                f"{ts_code:<12} {close:>7.2f} {dist:>7.1f}% "
                f"{contrac:>7.1f}% {tight:>6.1f}% "
                f"{'Y':>8} {score:>6.1f}" if vol_shrk else
                f"{ts_code:<12} {close:>7.2f} {dist:>7.1f}% "
                f"{contrac:>7.1f}% {tight:>6.1f}% "
                f"{'N':>8} {score:>6.1f}"
            )
        print(f"{'='*70}")
        return

    # ── Single stock mode ──
    if args.code:
        df = fetch_prices(args.code, days=300)
        if df.empty:
            print(f"No data for {args.code}")
            return
        result = detect_vcp(df, args.code)
        if result:
            print(f"\nVCP found for {args.code}:")
            for k, v in result.items():
                print(f"  {k}: {v}")
        else:
            print(f"No VCP pattern found for {args.code}")
        return
    
    # ── Full scan mode ──
    logger.info("Starting VCP scan for STAR Market...")
    results = scan_kc_stocks(top_n=args.top)
    print_results(results)
    
    # Save to database
    if results:
        scan_date = results[0]['date'] if results else datetime.now().strftime('%Y%m%d')
        save_results(results, scan_date)
        print(f"\nResults saved to: {DB_PATH}")
        print(f"Query with: python main.py --query latest")


if __name__ == '__main__':
    main()
