"""
Alpha Oracle - Stock Price Prediction System
Uses TimesFM for zero-shot forecasting and sector resonance detection
"""

import os
import sys
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Tuple
import pandas as pd
import numpy as np
from dotenv import load_dotenv

load_dotenv()

# ── core 路径注入 ──
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
from core.paths import Paths
from core.logging_cfg import get_logger

logger = get_logger(__name__)

DB_PATH = Paths.AlphaOracle.db


# ─────────────────────────────────────────────
# DB init & save
# ─────────────────────────────────────────────

def init_db():
    """Initialize SQLite database"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute('''
        CREATE TABLE IF NOT EXISTS alpha_results (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_date       TEXT NOT NULL,
            ts_code         TEXT NOT NULL,
            trade_date      TEXT NOT NULL,
            current_price   REAL,
            predicted_mean  REAL,
            predicted_change REAL,
            signal          TEXT,
            resonance_type  TEXT,
            resonance_confidence REAL,
            positive_ratio  REAL,
            volume_ratio    REAL,
            UNIQUE(scan_date, ts_code)
        )
    ''')
    conn.commit()
    conn.close()


def save_results(results: List[Dict], scan_date: str = None):
    """Save alpha oracle results to SQLite"""
    if not results:
        logger.info("No results to save")
        return

    scan_date = scan_date or datetime.now().strftime('%Y%m%d')
    init_db()

    conn = sqlite3.connect(DB_PATH)
    saved = 0
    for r in results:
        if 'error' in r:
            continue
        resonance = r.get('resonance', {})
        prediction = r.get('prediction', {})
        preds = prediction.get('predictions', [])
        predicted_mean = float(np.mean(preds)) if preds else None

        conn.execute('''
            INSERT OR REPLACE INTO alpha_results
            (scan_date, ts_code, trade_date, current_price, predicted_mean,
             predicted_change, signal, resonance_type, resonance_confidence,
             positive_ratio, volume_ratio)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            scan_date,
            r['ts_code'],
            r['trade_date'],
            r.get('current_price'),
            predicted_mean,
            r.get('predicted_change'),
            r.get('signal'),
            resonance.get('type'),
            resonance.get('confidence'),
            resonance.get('positive_ratio'),
            resonance.get('volume_ratio'),
        ))
        saved += 1

    conn.commit()
    conn.close()
    logger.info(f"Saved {saved} results to {DB_PATH}")


# ─────────────────────────────────────────────
# Tushare data fetching
# ─────────────────────────────────────────────

def fetch_stock_prices(ts_code: str, days: int = 120) -> pd.DataFrame:
    """Fetch daily price data via Tushare"""
    try:
        import tushare as ts
        token = os.getenv('TUSHARE_TOKEN')
        if not token:
            logger.warning("TUSHARE_TOKEN not set, using mock data")
            return pd.DataFrame()

        pro = ts.pro_api(token)
        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=days + 60)).strftime('%Y%m%d')

        df = pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
        if df is not None and not df.empty:
            df = df.sort_values('trade_date').reset_index(drop=True)
            return df.tail(days)
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"Failed to fetch prices for {ts_code}: {e}")
        return pd.DataFrame()


def fetch_stock_list(market: str = 'kcb') -> List[str]:
    """
    Fetch stock list via Tushare.
    market: 'kcb'（科创板全量）| 'kc50'（科创50成分）|
            'hs300' | 'zz500' | 'all'
    """
    try:
        import tushare as ts
        token = os.getenv('TUSHARE_TOKEN')
        if not token:
            logger.warning("TUSHARE_TOKEN not set")
            return []

        pro = ts.pro_api(token)

        if market == 'kcb':
            # 科创板：688 开头，上交所上市
            df = pro.stock_basic(exchange='SSE', list_status='L',
                                 fields='ts_code,name')
            if df is not None and not df.empty:
                kc = df[df['ts_code'].str.startswith('688')]
                logger.info(f"Found {len(kc)} 科创板 stocks")
                return kc['ts_code'].tolist()
            return []

        elif market == 'kc50':
            # 科创50指数成分股
            df = pro.index_weight(index_code='000688.SH',
                                  trade_date=datetime.now().strftime('%Y%m%d'))
            if df is None or df.empty:
                # 回退：取近一个月内有效的最近一期
                end = datetime.now().strftime('%Y%m%d')
                start = (datetime.now() - timedelta(days=40)).strftime('%Y%m%d')
                df = pro.index_weight(index_code='000688.SH',
                                      start_date=start, end_date=end)
            if df is not None and not df.empty:
                codes = df['con_code'].dropna().unique().tolist()
                logger.info(f"Found {len(codes)} 科创50 stocks")
                return codes
            return []

        elif market == 'hs300':
            df = pro.index_weight(index_code='399300.SZ',
                                  trade_date=datetime.now().strftime('%Y%m%d'))
            if df is None or df.empty:
                df = pro.hs300s()
            return df['con_code'].dropna().tolist() if df is not None and not df.empty else []

        elif market == 'zz500':
            df = pro.index_weight(index_code='000905.SH',
                                  trade_date=datetime.now().strftime('%Y%m%d'))
            return df['con_code'].dropna().tolist() if df is not None and not df.empty else []

        else:  # 'all'
            df = pro.stock_basic(exchange='', list_status='L',
                                 fields='ts_code,name,market')
            return df['ts_code'].dropna().tolist() if df is not None and not df.empty else []

    except Exception as e:
        logger.error(f"Failed to fetch stock list: {e}")
        return []


# ─────────────────────────────────────────────
# TimesFM predictor
# ─────────────────────────────────────────────

class TimesFMPredictor:
    def __init__(self, model_path: str = None):
        self.model_path = model_path
        self.model = None

    def load_model(self):
        """Load TimesFM model"""
        try:
            logger.info("Loading TimesFM model...")
            from timesfm import TimesFm

            self.model = TimesFm(
                context_len=128,
                horizon_len=30,
                per_core_batch_size=32,
                num_hypotheses=1
            )
            self.model.load_from_checkpoint(
                checkpoint='google/timesfm-1.0-200m'
            )
            logger.info("TimesFM model loaded successfully")
        except ImportError:
            logger.warning("timesfm not installed, using statistical predictions")
        except Exception as e:
            logger.error(f"Failed to load TimesFM: {e}")

    def predict(self, prices: pd.Series, horizon: int = 30) -> Dict:
        """Generate price predictions"""
        if self.model is None:
            self.load_model()

        if self.model is None:
            return self._stat_predict(prices, horizon)

        try:
            values = prices.values[-128:]
            forecast = self.model.forecast(values)

            return {
                'predictions': forecast.mean(axis=0).tolist(),
                'lower': forecast.min(axis=0).tolist(),
                'upper': forecast.max(axis=0).tolist(),
                'horizon': horizon
            }
        except Exception as e:
            logger.error(f"Prediction failed: {e}")
            return self._stat_predict(prices, horizon)

    def _stat_predict(self, prices: pd.Series, horizon: int) -> Dict:
        """Statistical trend-based prediction (fallback)"""
        if len(prices) < 5:
            last = prices.iloc[-1] if len(prices) > 0 else 100
            return {
                'predictions': [last] * horizon,
                'lower': [last * 0.95] * horizon,
                'upper': [last * 1.05] * horizon,
                'horizon': horizon
            }

        # Linear regression trend
        y = prices.values[-min(60, len(prices)):]
        x = np.arange(len(y))
        slope, intercept = np.polyfit(x, y, 1)

        last_price = prices.iloc[-1]
        predictions = []
        for i in range(1, horizon + 1):
            pred = last_price + slope * i
            predictions.append(float(pred))

        # Residual std for confidence bands
        y_fit = slope * x + intercept
        residuals = y - y_fit
        std = np.std(residuals) if len(residuals) > 1 else last_price * 0.02

        return {
            'predictions': predictions,
            'lower': [p - 1.5 * std for p in predictions],
            'upper': [p + 1.5 * std for p in predictions],
            'horizon': horizon
        }


# ─────────────────────────────────────────────
# Sector Resonance
# ─────────────────────────────────────────────

class SectorResonance:
    def __init__(self, db_path: str = None):
        self.db_path = db_path

    def get_sector_prices(self, trade_date: str) -> pd.DataFrame:
        """Get sector prices: try Tushare first, then DB, then mock"""
        df = self._fetch_sector_from_tushare(trade_date)
        if not df.empty:
            return df

        if self.db_path and os.path.exists(self.db_path):
            try:
                conn = sqlite3.connect(self.db_path)
                df = pd.read_sql_query(
                    "SELECT * FROM board_daily_prices WHERE trade_date = ?",
                    conn, params=(trade_date,)
                )
                conn.close()
                if not df.empty:
                    return df
            except Exception as e:
                logger.error(f"Failed to get sector prices from db: {e}")

        return self._get_mock_sectors()

    def _fetch_sector_from_tushare(self, trade_date: str) -> pd.DataFrame:
        """Fetch sector index data from Tushare"""
        try:
            import tushare as ts
            token = os.getenv('TUSHARE_TOKEN')
            if not token:
                return pd.DataFrame()

            pro = ts.pro_api(token)

            # SW industry level-1 index codes
            sw_codes = [
                '801010.SI', '801020.SI', '801030.SI', '801040.SI',
                '801050.SI', '801080.SI', '801110.SI', '801120.SI',
                '801130.SI', '801140.SI', '801150.SI', '801160.SI',
                '801170.SI', '801180.SI', '801200.SI', '801210.SI',
                '801230.SI', '801710.SI', '801720.SI', '801730.SI',
                '801740.SI', '801750.SI', '801760.SI', '801770.SI',
                '801780.SI', '801790.SI', '801880.SI', '801890.SI',
            ]

            rows = []
            for code in sw_codes:
                try:
                    df = pro.index_daily(ts_code=code, start_date=trade_date,
                                         end_date=trade_date)
                    if df is not None and not df.empty:
                        rows.append(df.iloc[0])
                except Exception:
                    continue

            if rows:
                result = pd.DataFrame(rows)
                result = result.rename(columns={'ts_code': 'ts_code'})
                return result

            return pd.DataFrame()

        except Exception as e:
            logger.error(f"Failed to fetch sector data from Tushare: {e}")
            return pd.DataFrame()

    def _get_mock_sectors(self) -> pd.DataFrame:
        """Generate mock sector data"""
        import random
        sectors = [
            '801010', '801020', '801030', '801040', '801050',
            '801080', '801110', '801120', '801150', '801160',
            '801210', '801230', '801720', '801730', '801880'
        ]
        data = []
        for s in sectors:
            data.append({
                'ts_code': s,
                'close': random.uniform(2000, 4000),
                'vol': random.uniform(5000000, 15000000),
                'amount': random.uniform(100, 500),
                'pct_chg': random.uniform(-3, 3)
            })
        return pd.DataFrame(data)

    def detect_resonance(self, sectors: pd.DataFrame) -> Dict:
        """Detect sector resonance patterns"""
        if sectors.empty:
            return {}

        sectors = sectors.copy()

        # Use pct_chg column if available, otherwise compute from close
        if 'pct_chg' not in sectors.columns:
            sectors['pct_chg'] = sectors['close'].pct_change() * 100

        valid = sectors.dropna(subset=['pct_chg'])
        if valid.empty:
            return {'type': 'neutral'}

        positive_count = (valid['pct_chg'] > 0).sum()
        negative_count = (valid['pct_chg'] < 0).sum()
        total = positive_count + negative_count

        if total == 0:
            return {'type': 'neutral'}

        positive_ratio = positive_count / total

        avg_volume = sectors['vol'].mean() if 'vol' in sectors.columns else 1
        current_volume = sectors['vol'].iloc[-1] if (
            'vol' in sectors.columns and len(sectors) > 0
        ) else avg_volume
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1

        if positive_ratio > 0.7 and volume_ratio > 1.2:
            resonance_type = 'strong_up'
            confidence = positive_ratio * min(volume_ratio, 2.0)
        elif positive_ratio > 0.55:
            resonance_type = 'weak_up'
            confidence = positive_ratio
        elif positive_ratio < 0.3 and volume_ratio > 1.2:
            resonance_type = 'strong_down'
            confidence = (1 - positive_ratio) * min(volume_ratio, 2.0)
        elif positive_ratio < 0.45:
            resonance_type = 'weak_down'
            confidence = 1 - positive_ratio
        else:
            resonance_type = 'neutral'
            confidence = 0.5

        return {
            'type': resonance_type,
            'confidence': round(confidence, 4),
            'positive_ratio': round(positive_ratio, 4),
            'volume_ratio': round(volume_ratio, 4),
            'sector_count': len(valid)
        }

    def find_leading_sectors(self, sectors: pd.DataFrame, top_n: int = 5) -> List[Dict]:
        """Find leading sectors by pct_chg"""
        if sectors.empty:
            return []

        sectors = sectors.copy()
        if 'pct_chg' not in sectors.columns:
            sectors['pct_chg'] = sectors['close'].pct_change() * 100

        sectors = sectors.sort_values('pct_chg', ascending=False)
        return sectors.head(top_n)[['ts_code', 'pct_chg']].to_dict('records')


# ─────────────────────────────────────────────
# Alpha Oracle
# ─────────────────────────────────────────────

class AlphaOracle:
    def __init__(self, db_path: str = None):
        self.predictor = TimesFMPredictor()
        self.sector_resonance = SectorResonance(db_path)

    def analyze(self, ts_code: str, prices: pd.DataFrame, trade_date: str = None) -> Dict:
        """Full analysis for a stock"""
        trade_date = trade_date or datetime.now().strftime('%Y%m%d')

        if prices.empty or len(prices) < 30:
            return {'error': 'Insufficient data', 'ts_code': ts_code}

        price_series = prices['close']

        prediction = self.predictor.predict(price_series)

        sectors = self.sector_resonance.get_sector_prices(trade_date)
        resonance = self.sector_resonance.detect_resonance(sectors)
        leading = self.sector_resonance.find_leading_sectors(sectors)

        current_price = float(price_series.iloc[-1])
        prediction_mean = float(np.mean(prediction['predictions']))

        change_pct = (prediction_mean - current_price) / current_price * 100

        return {
            'ts_code': ts_code,
            'trade_date': trade_date,
            'current_price': round(current_price, 2),
            'prediction': prediction,
            'predicted_change': round(change_pct, 2),
            'resonance': resonance,
            'leading_sectors': leading,
            'signal': 'bullish' if change_pct > 5 else 'bearish' if change_pct < -5 else 'neutral'
        }

    def generate_chart(self, analysis: Dict) -> str:
        """Generate HTML chart"""
        prediction = analysis.get('prediction', {})
        predictions = prediction.get('predictions', [])

        if not predictions:
            return "<html><body>No data</body></html>"

        import json

        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Alpha Oracle Prediction - {analysis.get('ts_code')}</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
</head>
<body>
    <h2>Price Prediction - {analysis.get('ts_code')}</h2>
    <p>Signal: {analysis.get('signal')}</p>
    <p>Predicted Change: {analysis.get('predicted_change', 0):.2f}%</p>
    <div id="chart"></div>
    <script>
        var predictions = {json.dumps(predictions)};
        var lower = {json.dumps(prediction.get('lower', []))};
        var upper = {json.dumps(prediction.get('upper', []))};
        var x = predictions.map((_, i) => i + 1);

        Plotly.newPlot('chart', [
            {{
                x: x, y: upper,
                type: 'scatter', mode: 'lines',
                line: {{color: 'rgba(0,100,255,0.2)'}},
                name: 'Upper', showlegend: false
            }},
            {{
                x: x, y: lower,
                type: 'scatter', mode: 'lines',
                fill: 'tonexty',
                fillcolor: 'rgba(0,100,255,0.1)',
                line: {{color: 'rgba(0,100,255,0.2)'}},
                name: 'Lower', showlegend: false
            }},
            {{
                x: x, y: predictions,
                type: 'scatter', mode: 'lines+markers',
                line: {{color: 'blue', width: 2}},
                name: 'Predicted'
            }}
        ]);
    </script>
</body>
</html>"""

        return html


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def main():
    import argparse
    from core.logging_cfg import setup_logging
    setup_logging(project="alpha-oracle")

    parser = argparse.ArgumentParser(description='Alpha Oracle')
    parser.add_argument('--predict', type=str, metavar='CODE',
                        help='单股深度预测，打印完整分析详情，e.g. --predict 688111.SH')
    parser.add_argument('--code', type=str, help='Stock code, e.g. 000001.SZ（同 --predict，兼容旧用法）')
    parser.add_argument('--codes', type=str, help='Comma-separated stock codes')
    parser.add_argument('--market', type=str, default='kcb',
                        help='Batch market: kcb（科创板，默认）| kc50 | hs300 | zz500 | all')
    parser.add_argument('--top', type=int, default=50,
                        help='Max stocks to scan when using --market')
    parser.add_argument('--days', type=int, default=120, help='Historical days')
    parser.add_argument('--save', action='store_true', default=True,
                        help='Save results to SQLite (default: True)')
    parser.add_argument('--chart', action='store_true',
                        help='Generate HTML chart for single-stock mode')
    args = parser.parse_args()

    oracle = AlphaOracle()
    scan_date = datetime.now().strftime('%Y%m%d')

    # ── 单股深度预测模式 ──
    single_code = args.predict or args.code
    if single_code:
        single_code = single_code.strip()
        logger.info(f"Single-stock prediction: {single_code}")
        prices = fetch_stock_prices(single_code, days=args.days)
        if prices.empty:
            print(f"No data for {single_code}")
            return

        analysis = oracle.analyze(single_code, prices, trade_date=scan_date)

        if 'error' in analysis:
            print(f"Error: {analysis['error']}")
            return

        pred = analysis['prediction']
        resonance = analysis.get('resonance', {})
        leading = analysis.get('leading_sectors', [])

        print(f"\n{'='*60}")
        print(f"  Alpha Oracle — Single Stock Prediction")
        print(f"{'='*60}")
        print(f"  Stock         : {analysis['ts_code']}")
        print(f"  Trade Date    : {analysis['trade_date']}")
        print(f"  Current Price : {analysis['current_price']:.2f}")
        print(f"  Pred Mean(30d): {float(np.mean(pred['predictions'])):.2f}")
        print(f"  Pred Change   : {analysis['predicted_change']:+.2f}%")
        print(f"  Signal        : {analysis['signal'].upper()}")
        print(f"{'─'*60}")
        print(f"  Forecast (next {pred['horizon']} days):")
        preds = pred['predictions']
        lows  = pred.get('lower', preds)
        highs = pred.get('upper', preds)
        print(f"  {'Day':>4}  {'Low':>10}  {'Mid':>10}  {'High':>10}")
        for i, (lo, mid, hi) in enumerate(zip(lows, preds, highs), 1):
            print(f"  {i:>4}  {lo:>10.2f}  {mid:>10.2f}  {hi:>10.2f}")
        print(f"{'─'*60}")
        print(f"  Sector Resonance:")
        print(f"    Type       : {resonance.get('type', 'N/A')}")
        print(f"    Confidence : {resonance.get('confidence', 'N/A')}")
        print(f"    Up ratio   : {resonance.get('positive_ratio', 'N/A')}")
        print(f"    Vol ratio  : {resonance.get('volume_ratio', 'N/A')}")
        if leading:
            print(f"  Leading Sectors:")
            for s in leading:
                print(f"    {s.get('ts_code',''):<14} {s.get('pct_chg', 0):+.2f}%")
        print(f"{'='*60}\n")

        if args.save:
            save_results([analysis], scan_date)

        if args.chart:
            chart_html = oracle.generate_chart(analysis)
            chart_path = Paths.AlphaOracle.data / f"{single_code.replace('.', '_')}_{scan_date}.html"
            chart_path.parent.mkdir(parents=True, exist_ok=True)
            chart_path.write_text(chart_html, encoding='utf-8')
            logger.info(f"Chart saved to {chart_path}")
        return

    # ── Build stock list for batch scan ──
    if args.codes:
        stock_list = [c.strip() for c in args.codes.split(',') if c.strip()]
    else:
        logger.info(f"Fetching stock list for market: {args.market}")
        stock_list = fetch_stock_list(args.market)
        if not stock_list:
            logger.error("Failed to fetch stock list, aborting")
            return
        stock_list = stock_list[:args.top]
        logger.info(f"Will scan {len(stock_list)} stocks")

    results = []

    for ts_code in stock_list:
        logger.info(f"Analyzing {ts_code}...")
        prices = fetch_stock_prices(ts_code, days=args.days)

        if prices.empty:
            logger.warning(f"  No data for {ts_code}, skipping")
            continue

        analysis = oracle.analyze(ts_code, prices, trade_date=scan_date)

        if 'error' not in analysis:
            results.append(analysis)
            logger.info(
                f"  {ts_code} | price={analysis['current_price']:.2f} "
                f"| change={analysis['predicted_change']:+.2f}% "
                f"| signal={analysis['signal']}"
            )

            if args.chart and len(stock_list) == 1:
                chart_html = oracle.generate_chart(analysis)
                chart_path = Paths.AlphaOracle.data / f"{ts_code.replace('.', '_')}_{scan_date}.html"
                chart_path.parent.mkdir(parents=True, exist_ok=True)
                chart_path.write_text(chart_html, encoding='utf-8')
                logger.info(f"Chart saved to {chart_path}")
        else:
            logger.warning(f"  {ts_code}: {analysis['error']}")

    # ── Save ──
    if args.save and results:
        save_results(results, scan_date)

    # ── Summary ──
    print(f"\n{'='*55}")
    print(f"  Alpha Oracle Analysis  ({scan_date})")
    print(f"{'='*55}")
    print(f"  Scanned : {len(stock_list)} stocks")
    print(f"  Results : {len(results)}")

    if results:
        bullish = [r for r in results if r['signal'] == 'bullish']
        bearish = [r for r in results if r['signal'] == 'bearish']
        neutral = [r for r in results if r['signal'] == 'neutral']
        print(f"  Bullish : {len(bullish)}")
        print(f"  Bearish : {len(bearish)}")
        print(f"  Neutral : {len(neutral)}")

        print(f"\n{'─'*55}")
        print(f"  {'Stock':<14} {'Price':>8} {'Pred Chg':>10} {'Signal':<10} {'Resonance'}")
        print(f"{'─'*55}")
        for r in sorted(results, key=lambda x: x['predicted_change'], reverse=True):
            res_type = r.get('resonance', {}).get('type', 'N/A')
            print(
                f"  {r['ts_code']:<14} {r['current_price']:>8.2f} "
                f"{r['predicted_change']:>+9.2f}% {r['signal']:<10} {res_type}"
            )

    if args.save and results:
        print(f"\n  Data saved to: {DB_PATH}")
    print(f"{'='*55}\n")


if __name__ == '__main__':
    main()
