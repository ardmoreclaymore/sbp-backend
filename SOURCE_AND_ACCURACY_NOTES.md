# SBP source + accuracy notes

## Sources used by this patch
- Bazaar: official Hypixel Bazaar API.
- Active Auction House: official Hypixel Auctions API, grouped into item-level AH rows.
- AH history/enrichment: Coflnet/SkyCofl optional per-item enrichment for selected high-priority items.
- Current mayor/election: official Hypixel election API first, SkyBlock.Tools fallback.
- Current money-making/meta text: OutcroCalculator public page when visible.

## Why AH uses Hypixel + optional Coflnet
Coflnet is excellent for history and sold-auction analysis, but hitting Coflnet for 20,000 items every 5 minutes would be heavy and risky. This patch uses the official Hypixel AH sweep for broad coverage, then Coflnet only for high-priority enrichment.

## Accuracy honesty
The prediction engine is explainable and backtest-ready, but it is not 99% verified yet. It must collect historical rows, run `backtest.py`, and calibrate certainty using actual hits/misses.

## Manual boosting detection added
The predictor reduces confidence when it sees:
- huge movement on thin volume,
- wide Bazaar spreads,
- thin one-sided orders,
- AH floor far above/below median,
- single cheap listing far below second-lowest,
- too few AH listings,
- high volatility from sold-auction analysis.

## Website graph behavior
The chart draws historical data in green and predicted future path in yellow. The selected point section uses yellow styling to show future estimates have not happened yet.
