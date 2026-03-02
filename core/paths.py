"""
core/paths.py — 唯一的路径定义中心

使用方式（任意项目/脚本）：
    from core.paths import Paths
    db = Paths.data("alpha-oracle") / "alpha_oracle.db"
    csv = Paths.data("emotion-cycle") / "emotion_history.csv"

原则：
  - 所有运行时数据（DB / CSV / 报告 / 日志）统一存放在根目录 data/{project-name}/
  - projects/{name}/ 目录下只放代码，不放数据
  - skills/ 目录由 Paths.setup_sys_path() 注入，消除所有 sys.path hack
"""

import os
import sys
from pathlib import Path

# 项目根目录（本文件位于 core/，向上一级即为根）
ROOT = Path(__file__).resolve().parent.parent


class Paths:
    """全局路径中枢，所有路径均从 ROOT 派生，不含任何硬编码绝对路径。"""

    # ── 顶层目录 ──────────────────────────────────
    root     = ROOT
    core     = ROOT / "core"
    projects = ROOT / "projects"
    skills   = ROOT / "skills"
    data     = ROOT / "data"          # 所有运行时数据的根

    # ── 单个项目的数据目录 ─────────────────────────
    @staticmethod
    def project_data(name: str) -> Path:
        """返回 data/{name}/ 并确保目录存在。"""
        d = ROOT / "data" / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ── 常用快捷方式 ───────────────────────────────
    @staticmethod
    def db(project: str, filename: str) -> Path:
        """data/{project}/{filename}.db"""
        return Paths.project_data(project) / filename

    @staticmethod
    def reports(project: str) -> Path:
        """data/{project}/reports/，并确保目录存在。"""
        d = Paths.project_data(project) / "reports"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @staticmethod
    def logs(project: str) -> Path:
        """data/{project}/logs/，并确保目录存在。"""
        d = Paths.project_data(project) / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ── 具体项目路径（消除各模块重复定义）────────────
    class AlphaOracle:
        db   = ROOT / "data" / "alpha-oracle" / "alpha_oracle.db"
        data = ROOT / "data" / "alpha-oracle"

    class EmotionCycle:
        data    = ROOT / "data" / "emotion-cycle"
        history = ROOT / "data" / "emotion-cycle" / "emotion_history.csv"
        limits  = ROOT / "data" / "emotion-cycle" / "limit_history.csv"
        reports = ROOT / "data" / "emotion-cycle" / "reports"

    class VcpScanner:
        db   = ROOT / "data" / "vcp-scanner" / "vcp.db"
        data = ROOT / "data" / "vcp-scanner"

    class StockRps:
        db   = ROOT / "data" / "stock-rps" / "rps.db"
        data = ROOT / "data" / "stock-rps"

    class MarketAnalysis:
        data    = ROOT / "data" / "market-analysis"
        reports = ROOT / "data" / "market-analysis" / "reports"

    class IcePointResonance:
        data    = ROOT / "data" / "ice-point-resonance"
        reports = ROOT / "data" / "ice-point-resonance" / "reports"

    # ── sys.path 统一注入 ──────────────────────────
    @staticmethod
    def setup_sys_path():
        """
        统一注入 sys.path，消除各文件中的 sys.path.insert hack。
        在任意入口脚本顶部调用一次即可。
        """
        for p in [str(ROOT), str(ROOT / "projects"), str(ROOT / "skills")]:
            if p not in sys.path:
                sys.path.insert(0, p)

    # ── 目录初始化 ─────────────────────────────────
    @staticmethod
    def ensure_all():
        """创建所有项目的 data 目录，启动时调用一次。"""
        dirs = [
            Paths.AlphaOracle.data,
            Paths.EmotionCycle.data,
            Paths.EmotionCycle.reports,
            Paths.VcpScanner.data,
            Paths.StockRps.data,
            Paths.MarketAnalysis.data,
            Paths.MarketAnalysis.reports,
            Paths.IcePointResonance.data,
            Paths.IcePointResonance.reports,
        ]
        for d in dirs:
            Path(d).mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    Paths.ensure_all()
    print(f"ROOT     : {Paths.root}")
    print(f"projects : {Paths.projects}")
    print(f"data     : {Paths.data}")
    print(f"alpha-oracle db : {Paths.AlphaOracle.db}")
    print(f"emotion-cycle   : {Paths.EmotionCycle.history}")
    print(f"vcp-scanner db  : {Paths.VcpScanner.db}")
    print(f"stock-rps db    : {Paths.StockRps.db}")
