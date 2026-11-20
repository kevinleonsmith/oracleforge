"""OracleForge resolution watcher.

Pokes the permissionless ``MarketEngine.resolve(marketId)`` once a market is past
``closeAt`` and its oracle is ready, then archives the settlement as an oracle
report. The off-chain driver that Chainlink Automation replaces in production.
"""
from .watcher import Watcher, TickOutcome
from .planner import plan, plan_one
from .models import Market, Decision, Outcome, Status, Action, OracleReport

__all__ = [
    "Watcher", "TickOutcome", "plan", "plan_one",
    "Market", "Decision", "Outcome", "Status", "Action", "OracleReport",
]
__version__ = "0.1.0"
