"""
Market Technical Analysis
Daily and weekly market analysis reports
"""

import os
import sys
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import pandas as pd

logger = logging.getLogger(__name__)


class MarketAnalyzer:
    def __init__(self, db_path: str = None):
        self.db_path = db_path
    
    def fetch_market_data(self, index_code: str = '000001.SH', days: int = 60) -> pd.DataFrame:
        """Fetch market index data"""
        try:
            import tushare as ts
            from dotenv import load_dotenv
            
            load_dotenv()
            token = os.getenv('TUSHARE_TOKEN')
            
            if not token:
                return self._mock_data(days)
            
            pro = ts.pro_api(token)
            
            end_date = datetime.now().strftime('%Y%m%d')
            start_date = (datetime.now() - timedelta(days=days + 30)).strftime('%Y%m%d')
            
            df = pro.daily(ts_code=index_code, start_date=start_date, end_date=end_date)
            
            if df is not None and not df.empty:
                df = df.sort_values('trade_date')
                return df[-days:]
            
            return self._mock_data(days)
            
        except Exception as e:
            logger.error(f"Failed to fetch market data: {e}")
            return self._mock_data(days)
    
    def _mock_data(self, days: int) -> pd.DataFrame:
        """Generate mock market data"""
        import random
        
        dates = pd.date_range(end=datetime.now(), periods=days, freq='D')
        base = 3200
        
        data = []
        current = base
        for d in dates:
            if d.weekday() < 5:
                change = random.uniform(-0.02, 0.025)
                current = current * (1 + change)
                
                volatility = random.uniform(0.015, 0.035)
                high = current * (1 + volatility)
                low = current * (1 - volatility)
                
                data.append({
                    'trade_date': d.strftime('%Y%m%d'),
                    'open': current,
                    'high': high,
                    'low': low,
                    'close': current * random.uniform(0.995, 1.005),
                    'vol': random.uniform(250000000, 400000000),
                    'amount': current * random.uniform(250000000, 400000000)
                })
        
        return pd.DataFrame(data)
    
    def calculate_ma(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate moving averages"""
        df = df.copy()
        
        for period in [5, 10, 20, 60]:
            df[f'ma{period}'] = df['close'].rolling(period).mean()
        
        return df
    
    def calculate_macd(self, df: pd.DataFrame) -> pd.DataFrame:
        """Calculate MACD"""
        df = df.copy()
        
        ema12 = df['close'].ewm(span=12, adjust=False).mean()
        ema26 = df['close'].ewm(span=26, adjust=False).mean()
        
        df['macd'] = ema12 - ema26
        df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
        df['histogram'] = df['macd'] - df['signal']
        
        return df
    
    def detect_bearish_divergence(self, df: pd.DataFrame) -> Optional[Dict]:
        """Detect bearish divergence (price higher, MACD lower)"""
        if len(df) < 60:
            return None
        
        recent = df.tail(60)
        
        price_high = recent['high'].max()
        price_high_idx = recent['high'].idxmax()
        
        macd_at_high = recent.loc[price_high_idx, 'macd']
        
        current_price = recent['close'].iloc[-1]
        current_macd = recent['macd'].iloc[-1]
        
        if current_price > price_high * 0.98 and current_macd < macd_at_high * 0.8:
            return {
                'type': 'bearish_divergence',
                'price_high': price_high,
                'current_price': current_price,
                'macd_at_high': macd_at_high,
                'current_macd': current_macd,
                'strength': abs(current_macd - macd_at_high) / abs(macd_at_high)
            }
        
        return None
    
    def analyze_trend(self, df: pd.DataFrame) -> Dict:
        """Analyze market trend"""
        if len(df) < 20:
            return {'trend': 'unknown'}
        
        ma5 = df['ma5'].iloc[-1]
        ma20 = df['ma20'].iloc[-1]
        ma60 = df['ma60'].iloc[-1] if 'ma60' in df.columns else ma20
        
        current = df['close'].iloc[-1]
        
        if current > ma5 > ma20 > ma60:
            trend = 'strong_uptrend'
        elif current > ma5 > ma20:
            trend = 'uptrend'
        elif current < ma5 < ma20 < ma60:
            trend = 'strong_downtrend'
        elif current < ma5 < ma20:
            trend = 'downtrend'
        else:
            trend = 'sideways'
        
        return {
            'trend': trend,
            'ma5': ma5,
            'ma20': ma20,
            'ma60': ma60,
            'current': current,
            'distance_from_ma20': (current - ma20) / ma20 * 100
        }
    
    def generate_report(self) -> str:
        """Generate market analysis report"""
        df = self.fetch_market_data()
        df = self.calculate_ma(df)
        df = self.calculate_macd(df)
        
        divergence = self.detect_bearish_divergence(df)
        trend = self.analyze_trend(df)
        
        current = df.iloc[-1]
        
        report = f"""# 市场技术分析报告
日期: {datetime.now().strftime('%Y-%m-%d')}

## 趋势分析
- 当前趋势: {trend['trend']}
- 收盘价: {current['close']:.2f}
- MA5: {trend['ma5']:.2f}
- MA20: {trend['ma20']:.2f}
- 偏离MA20: {trend['distance_from_ma20']:.2f}%

## MACD指标
- DIF: {current['macd']:.4f}
- DEA: {current['signal']:.4f}
- 柱状图: {current['histogram']:.4f}

"""
        
        if divergence:
            report += f"""## 风险提示
⚠️ 检测到顶背离信号:
- 价格新高: {divergence['price_high']:.2f}
- MACD对应值: {divergence['macd_at_high']:.4f}
- 当前MACD: {divergence['current_macd']:.4f}
- 背离强度: {divergence['strength']:.2f}

"""
        
        return report


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Market Analysis')
    parser.add_argument('--output', type=str, help='Output file path')
    args = parser.parse_args()
    
    analyzer = MarketAnalyzer()
    report = analyzer.generate_report()
    
    print(report)
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"\nReport saved to {args.output}")


if __name__ == '__main__':
    main()
