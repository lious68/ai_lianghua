"""
openclaw_config.py — 兼容性 shim
新代码请直接使用 core.paths.Paths，本文件仅保留旧接口以免报错。
"""

from core.paths import Paths as _P
from pathlib import Path

PROJECT_ROOT = _P.root

def get_mode():
    import os, platform
    mode = os.getenv('OPENCLAW_MODE', '').lower()
    if mode:
        return mode
    return 'dev' if platform.system().lower() == 'windows' else 'prod'

def get_workspace() -> Path:       return _P.root
def get_data_dir() -> Path:        return _P.data
def get_db_dir() -> Path:          return _P.StockRps.data
def get_projects_dir() -> Path:    return _P.projects
def get_rps_db_path() -> Path:     return _P.StockRps.db
def get_emotion_history_path() -> Path: return _P.EmotionCycle.history

def ensure_dirs():
    _P.ensure_all()

def print_config():
    print(f"Mode         : {get_mode()}")
    print(f"Project Root : {PROJECT_ROOT}")
    print(f"Data Dir     : {get_data_dir()}")
    print(f"RPS DB       : {get_rps_db_path()}")

if __name__ == '__main__':
    print_config()
