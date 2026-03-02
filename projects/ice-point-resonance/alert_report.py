"""
Ice Point Resonance Alert
Market ice point resonance early warning system
"""

import os
import sys
import logging
from datetime import datetime
from typing import Dict, List, Optional
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from emotion_cycle.data_fetcher import EmotionDataFetcher
from emotion_cycle.calculator import EmotionCalculator

logger = logging.getLogger(__name__)


class IcePointResonance:
    def __init__(self):
        self.fetcher = EmotionDataFetcher()
        self.calculator = EmotionCalculator()
    
    def detect_ice_point(self, ohlc_df: pd.DataFrame, limit_count: int, amount: float) -> bool:
        """Detect if market is at ice point"""
        if ohlc_df.empty:
            return False
        
        latest = ohlc_df.iloc[-1]
        
        cci = self.calculator.calculate_cci(ohlc_df)
        latest_cci = cci['cci'].iloc[-1]
        
        if latest_cci < -100 and amount < 500 and limit_count < 20:
            return True
        
        return False
    
    def detect_resonance(self, ohlc_df: pd.DataFrame, limit_count: int, amount: float) -> Dict:
        """Detect resonance conditions"""
        if ohlc_df.empty:
            return {}
        
        latest = ohlc_df.iloc[-1]
        
        cci = self.calculator.calculate_cci(ohlc_df)
        latest_cci = cci['cci'].iloc[-1]
        
        ohlc_with_ma = self.calculator.calculate_ma(ohlc_df)
        latest_ma10 = ohlc_with_ma['ma_10'].iloc[-1]
        latest_ma20 = ohlc_with_ma['ma_20'].iloc[-1]
        
        price_above_ma = latest['close'] > latest_ma20
        
        limit_ratio = limit_count / 1000 if limit_count > 0 else 0
        
        resonance_score = 0
        
        if latest_cci < -80:
            resonance_score += 2
        elif latest_cci < -50:
            resonance_score += 1
        
        if amount < 600:
            resonance_score += 2
        elif amount < 800:
            resonance_score += 1
        
        if limit_ratio < 0.05:
            resonance_score += 2
        elif limit_ratio < 0.1:
            resonance_score += 1
        
        if price_above_ma:
            resonance_score += 1
        
        return {
            'cci': latest_cci,
            'amount': amount,
            'limit_count': limit_count,
            'price_above_ma20': price_above_ma,
            'resonance_score': resonance_score,
            'resonance_level': 'strong' if resonance_score >= 6 else 'medium' if resonance_score >= 4 else 'weak'
        }
    
    def generate_alert(self) -> Optional[Dict]:
        """Generate ice point resonance alert"""
        trade_date = datetime.now().strftime('%Y%m%d')
        
        ohlc = self.fetcher.fetch_880005_ohlc()
        limit_df = self.fetcher.fetch_limit_up_stocks(trade_date)
        amount = self.fetcher.fetch_market_amount(trade_date)
        
        if ohlc.empty:
            return None
        
        is_ice_point = self.detect_ice_point(ohlc, len(limit_df), amount)
        
        resonance = self.detect_resonance(ohlc, len(limit_df), amount)
        
        if is_ice_point or resonance.get('resonance_score', 0) >= 5:
            return {
                'trade_date': trade_date,
                'is_ice_point': is_ice_point,
                'resonance': resonance,
                'alert_level': 'red' if is_ice_point else 'yellow'
            }
        
        return None


class IcePointReporter:
    def __init__(self, bot_token: str = None, chat_ids: List[str] = None):
        self.bot_token = bot_token or os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_ids = chat_ids or []
    
    def format_alert(self, alert: Dict) -> str:
        """Format alert message"""
        trade_date = alert['trade_date']
        resonance = alert['resonance']
        
        emoji = "🔴" if alert['alert_level'] == 'red' else "🟡"
        
        msg = f"{emoji} *冰点共振预警*\n"
        msg += f"📅 日期: {trade_date}\n\n"
        
        msg += "*共振指标:*\n"
        msg += f"  • CCI: `{resonance.get('cci', 0):.2f}`\n"
        msg += f"  • 成交额: `{resonance.get('amount', 0):.2f}亿`\n"
        msg += f"  • 涨停家数: `{resonance.get('limit_count', 0)}`\n"
        msg += f"  • 价格站上MA20: `{'是' if resonance.get('price_above_ma20') else '否'}`\n"
        msg += f"  • 共振得分: `{resonance.get('resonance_score', 0)}`\n"
        msg += f"  • 共振级别: *{resonance.get('resonance_level', 'N/A')}*\n\n"
        
        if alert['is_ice_point']:
            msg += "*⚠️ 强烈信号: 市场处于冰点状态*\n"
        
        return msg
    
    def send_alert(self, message: str):
        """Send alert via Telegram"""
        if not self.bot_token:
            logger.warning("TELEGRAM_BOT_TOKEN not configured")
            return
        
        try:
            import requests
            
            for chat_id in self.chat_ids:
                url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
                requests.post(url, json={
                    'chat_id': chat_id,
                    'text': message,
                    'parse_mode': 'Markdown'
                }, timeout=10)
                
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")


def main():
    detector = IcePointResonance()
    reporter = IcePointReporter()
    
    alert = detector.generate_alert()
    
    if alert:
        message = reporter.format_alert(alert)
        print(message)
        reporter.send_alert(message)
    else:
        print("No ice point resonance detected")


if __name__ == '__main__':
    main()
