"""OracleForge relayer.

Bridges the off-chain AI/Cartesi pipeline to on-chain markets: reads the committed
forecast notice for each AI proposal and submits ``createMarket`` to the
MarketEngine on Gnosis Chain as an authorized relayer.
"""
from .relayer import Relayer, RelayResult
from .mapping import build_create_market_args, CreateMarketArgs, SkipProposal

__all__ = [
    "Relayer", "RelayResult",
    "build_create_market_args", "CreateMarketArgs", "SkipProposal",
]
__version__ = "0.1.0"
