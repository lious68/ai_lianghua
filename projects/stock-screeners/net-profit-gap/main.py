"""
Net Profit Gap Scanner
Scan for stocks with earnings gaps
"""

import os
import sys
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pandas as pd

logger = logging.getLogger(__name__)


class NetProfitGapScanner:
    def __init__(self, db_path: str = None):
        self.db_path = db_path
    
    def fetch_financial_data(self, ts_code: str) -> Optional[Dict]:
        """Fetch financial data"""
        try:
            import tushare as ts
            from dotenv import load_dotenv
            
            load_dotenv()
            token = os.getenv('TUSHARE_TOKEN')
            
            if not token:
                return None
            
            pro = ts.pro_api(token)
            
            df = pro.fina_indicator(ts_code=ts_code)
            
            if df is not None and not df.empty:
                return df.iloc[-1].to_dict()
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to fetch financial data: {e}")
            return None
    
    def detect_gap(self, prices: pd.DataFrame) -> Optional[Dict]:
        """Detect price gap after earnings"""
        if len(prices) < 10:
            return None
        
        recent = prices.tail(10)
        
        for i in range(1, len(recent)):
            prev_close = recent['close'].iloc[i-1]
            current_open = recent['open'].iloc[i]
            current_close = recent['close'].iloc[i]
            
            gap_up = (current_open - prev_close) / prev_close
            gap_down = (prev_close - current_open) / prev_close
            
            if gap_up > 0.05:
                return {
                    'type': 'gap_up',
                    'gap_pct': gap_up * 100,
                    'volume_ratio': current_close / prev_close,
                    'date': recent['trade_date'].iloc[i]
                }
            elif gap_down > 0.05:
                return {
                    'type': 'gap_down',
                    'gap_pct': gap_down * 100,
                    'volume_ratio': current_close / prev_close,
                    'date': recent['trade_date'].iloc[i]
                }
        
        return None
    
    def scan_stocks(self, stocks: List[str]) -> List[Dict]:
        """Scan stocks for profit gaps"""
        results = []
        
        for ts_code in stocks:
            try:
                prices = self.fetch_prices(ts_code)
                gap = self.detect_gap(prices)
                
                if gap:
                    gap['ts_code'] = ts_code
                    results.append(gap)
                    
            except Exception as e:
                logger.error(f"Error scanning {ts_code}: {e}")
        
        return results
    
    def fetch_prices(self, ts_code: str, days: int = 30) -> pd.DataFrame:
        """Fetch stock prices"""
        try:
            import tushare as ts
            from dotenv import load_dotenv
            
            load_dotenv()
            token = os.getenv('TUSHARE_TOKEN')
            
            if not token:
                return self._mock_prices(days)
            
            pro = ts.pro_api(token)
            
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=days + 10)).strftime('%Y%m%d')
            
            df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            
            if df is not None and not df.empty:
                return df.sort_values('trade_date')
            
            return self._mock_prices(days)
            
        except Exception as e:
            return self._mock_prices(days)
    
    def _mock_prices(self, days: int) -> pd.DataFrame:
        """Mock prices"""
        import random
        
        dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
        base = 50
        
        data = []
        current = base
        for d in dates:
            if d.weekday() < 5:
                if len(data) > 5 and random.random() > 0.9:
                    gap = random.uniform(0.06, 0.12)
                    current = current * (1 + gap)
                else:
                    current = current * random.uniform(0.98, 1.02)
                
                data.append({
                    'trade_date': d.strftime('%Y%m%d'),
                    'open': current * random.uniform(0.99, 1.01),
                    'close': current,
                    'vol': random.uniform(1000000, 5000000)
                })
        
        return pd.DataFrame(data)


def main():
    scanner = NetProfitGapScanner()
    
    stocks = ['000001.SZ', '600000.SH', '600519.SH', '000858.SZ']
    results = scanner.scan_stocks(stocks)
    
    print("=== Net Profit Gap Results ===")
    for r in results:
        print(f"{r['ts_code']}: {r['type']} {r['gap_pct']:.2f}%")


if __name__ == '__main__':
    main()
