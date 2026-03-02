"""
Signal Tracker
Track trading signal performance and returns
"""

import os
import sys
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pandas as pd
import sqlite3

logger = logging.getLogger(__name__)


class SignalTracker:
    def __init__(self, db_path: str = None):
        if db_path is None:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            db_path = os.path.join(project_root, 'projects', 'stock-screeners', 'data', 'signals.db')
        
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Initialize database"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        conn = sqlite3.connect(self.db_path)
        conn.execute('''
            CREATE TABLE IF NOT EXISTS signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_code TEXT NOT NULL,
                signal_date TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                entry_price REAL,
                notes TEXT,
                UNIQUE(ts_code, signal_date)
            )
        ''')
        
        conn.execute('''
            CREATE TABLE IF NOT EXISTS returns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id INTEGER NOT NULL,
                exit_date TEXT,
                exit_price REAL,
                return_pct REAL,
                holding_days INTEGER,
                FOREIGN KEY(signal_id) REFERENCES signals(id)
            )
        ''')
        
        conn.commit()
        conn.close()
    
    def add_signal(self, ts_code: str, signal_type: str, entry_price: float, notes: str = ''):
        """Add a new signal"""
        conn = sqlite3.connect(self.db_path)
        
        signal_date = datetime.now().strftime('%Y%m%d')
        
        conn.execute('''
            INSERT OR REPLACE INTO signals (ts_code, signal_date, signal_type, entry_price, notes)
            VALUES (?, ?, ?, ?, ?)
        ''', (ts_code, signal_date, signal_type, entry_price, notes))
        
        conn.commit()
        conn.close()
    
    def update_return(self, ts_code: str, signal_date: str, exit_price: float):
        """Update return for a signal"""
        conn = sqlite3.connect(self.db_path)
        
        cursor = conn.execute('''
            SELECT id, entry_price FROM signals 
            WHERE ts_code = ? AND signal_date = ?
        ''', (ts_code, signal_date))
        
        row = cursor.fetchone()
        
        if row:
            signal_id, entry_price = row
            return_pct = (exit_price - entry_price) / entry_price * 100
            
            exit_date = datetime.now().strftime('%Y%m%d')
            holding_days = (datetime.now() - datetime.strptime(signal_date, '%Y%m%d')).days
            
            conn.execute('''
                INSERT INTO returns (signal_id, exit_date, exit_price, return_pct, holding_days)
                VALUES (?, ?, ?, ?, ?)
            ''', (signal_id, exit_date, exit_price, return_pct, holding_days))
            
            conn.commit()
        
        conn.close()
    
    def get_performance(self) -> Dict:
        """Get overall performance"""
        conn = sqlite3.connect(self.db_path)
        
        df = pd.read_sql_query('''
            SELECT s.*, r.return_pct, r.holding_days
            FROM signals s
            LEFT JOIN returns r ON s.id = r.signal_id
            ORDER BY s.signal_date DESC
        ''', conn)
        
        conn.close()
        
        if df.empty:
            return {'total_signals': 0, 'avg_return': 0}
        
        closed = df[df['return_pct'].notna()]
        
        return {
            'total_signals': len(df),
            'closed_signals': len(closed),
            'avg_return': closed['return_pct'].mean() if len(closed) > 0 else 0,
            'win_rate': (closed['return_pct'] > 0).sum() / len(closed) if len(closed) > 0 else 0,
            'best_return': closed['return_pct'].max() if len(closed) > 0 else 0,
            'worst_return': closed['return_pct'].min() if len(closed) > 0 else 0
        }


def main():
    tracker = SignalTracker()
    
    print("=== Signal Tracker ===")
    perf = tracker.get_performance()
    
    print(f"Total Signals: {perf['total_signals']}")
    print(f"Closed: {perf['closed_signals']}")
    print(f"Average Return: {perf['avg_return']:.2f}%")
    print(f"Win Rate: {perf['win_rate']*100:.1f}%")


if __name__ == '__main__':
    main()
