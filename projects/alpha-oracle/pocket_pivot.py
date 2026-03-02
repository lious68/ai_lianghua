"""
Pocket Pivot Scanner
Scan for pocket pivot buy points
"""

import os
import sys
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class PocketPivotScanner:
    def __init__(self, db_path: str = None):
        self.db_path = db_path
    
    def fetch_stock_prices(self, ts_code: str, days: int = 50) -> pd.DataFrame:
        """Fetch stock prices"""
        try:
            import tushare as ts
            from dotenv import load_dotenv
            
            load_dotenv()
            token = os.getenv('TUSHARE_TOKEN')
            
            if not token:
                return self._generate_mock_prices(days)
            
            pro = ts.pro_api(token)
            
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=days + 30)).strftime('%Y%m%d')
            
            df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            
            if df is not None and not df.empty:
                df = df.sort_values('trade_date')
                return df[-days:]
            
            return self._generate_mock_prices(days)
            
        except Exception as e:
            logger.error(f"Failed to fetch prices for {ts_code}: {e}")
            return self._generate_mock_prices(days)
    
    def _generate_mock_prices(self, days: int) -> pd.DataFrame:
        """Generate mock price data"""
        import random
        
        base_price = 50
        dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
        
        prices = []
        current = base_price
        for d in dates:
            if d.weekday() < 5:
                change = random.uniform(-0.05, 0.05)
                current = current * (1 + change)
                prices.append({
                    'trade_date': d.strftime('%Y%m%d'),
                    'open': current * random.uniform(0.98, 1.02),
                    'high': current * random.uniform(1.0, 1.05),
                    'low': current * random.uniform(0.95, 1.0),
                    'close': current,
                    'vol': random.uniform(1000000, 10000000),
                    'amount': current * random.uniform(1000000, 10000000)
                })
        
        return pd.DataFrame(prices)
    
    def calculate_vol_ma(self, prices: pd.DataFrame, period: int = 10) -> pd.DataFrame:
        """Calculate volume moving average"""
        prices = prices.copy()
        prices['vol_ma'] = prices['vol'].rolling(window=period).mean()
        return prices
    
    def detect_pocket_pivot(self, prices: pd.DataFrame, lookback: int = 30) -> Optional[Dict]:
        """Detect pocket pivot pattern"""
        if len(prices) < lookback:
            return None
        
        prices = self.calculate_vol_ma(prices)
        
        current_vol = prices['vol'].iloc[-1]
        current_close = prices['close'].iloc[-1]
        
        vol_ma = prices['vol_ma'].iloc[-1]
        
        if current_vol < vol_ma:
            return None
        
        recent_lows = prices['low'].iloc[-lookback:-1].min()
        
        if current_close > recent_lows:
            return None
        
        if prices['close'].iloc[-1] > prices['close'].iloc[-5]:
            pass
        else:
            return None
        
        gap_down = False
        for i in range(-10, 0):
            if prices['close'].iloc[i] < prices['close'].iloc[i-1] * 0.98:
                gap_down = True
                break
        
        if gap_down:
            return None
        
        current_high = prices['high'].iloc[-1]
        high_20 = prices['high'].iloc[-20:].max()
        
        if current_close < high_20 * 0.95:
            return None
        
        return {
            'date': prices['trade_date'].iloc[-1],
            'close': current_close,
            'volume': current_vol,
            'vol_ratio': current_vol / vol_ma if vol_ma > 0 else 0,
            'strength': (current_close / prices['close'].iloc[-5] - 1) * 100
        }
    
    def scan_stocks(self, stock_list: List[str]) -> List[Dict]:
        """Scan multiple stocks for pocket pivots"""
        results = []
        
        for ts_code in stock_list:
            try:
                prices = self.fetch_stock_prices(ts_code)
                
                pivot = self.detect_pocket_pivot(prices)
                
                if pivot:
                    pivot['ts_code'] = ts_code
                    results.append(pivot)
                    
            except Exception as e:
                logger.error(f"Error scanning {ts_code}: {e}")
                continue
        
        return sorted(results, key=lambda x: x.get('strength', 0), reverse=True)


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Pocket Pivot Scanner')
    parser.add_argument('--top', type=int, default=10, help='Number of top stocks to scan')
    args = parser.parse_args()
    
    scanner = PocketPivotScanner()
    
    mock_stocks = [
        '000001.SZ', '000002.SZ', '600000.SH', '600001.SH',
        '600004.SH', '600009.SH', '600016.SH', '600019.SH',
        '600028.SH', '600030.SH'
    ]
    
    results = scanner.scan_stocks(mock_stocks[:args.top])
    
    print("=== Pocket Pivot Results ===")
    for r in results:
        print(f"{r['ts_code']}: Close={r['close']:.2f}, Vol={r['vol_ratio']:.2f}x, Strength={r['strength']:.2f}%")


if __name__ == '__main__':
    main()
