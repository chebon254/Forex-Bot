# FxBot

Your Forex Chart strategy (interest-rate differential + COT commercials + market structure break), automated for **FBS MetaTrader 5 on Linux**.

```
 Linux (Python)                                   MetaTrader 5 (under Wine), logged in to FBS
 ┌──────────────────────────────┐   bias file   ┌──────────────────────────────────────────┐
 │ fxbot                        │  ──────────▶  │ FxBot EA                                 │
 │  • COT commercials (CFTC)    │  Common\Files │  • reads the weekly bias                 │
 │  • interest rates (your site)│               │  • finds swings, HH/HL/LH/LL, the MSB    │
 │  • your rules → BUY/SELL     │               │  • enters, stop + target on FBS's server │
 │  • backtests                 │               │  • risk per trade, max trades, daily cap │
 └──────────────────────────────┘               └──────────────────────────────────────────┘
        runs every 6 h (systemd timer)                  runs while MT5 is open
```

Why this split: the official MetaTrader5 Python package only works on Windows. An EA running *inside* MT5 is the most reliable way to trade (it runs the same under Wine, on Windows or on a VPS). Python on Linux does the internet work MT5 is bad at. The FBS web terminal cannot run bots, so use it only to watch trades.

## Your strategy → the bot's rules

| Your Forex Chart page says | What the bot does |
|---|---|
| Couple two currencies with the highest interest differential | Ranks all 28 pairs by the differential you earn in the trade direction ("carry") |
| Commercials above / below the zero basis line (the red line on Barchart) | Pulls the same numbers straight from the CFTC (Legacy COT report, commercials long − short). USD uses the Dollar Index contract, like Barchart. Within ±2% of open interest counts as flat |
| Coupled currencies must be on opposite sides of zero | Base above + quote below = **BUY**; base below + quote above = **SELL**; same side or flat = no trade |
| USD bullish vs weak CHF *because USD has the higher rate* | **Grade A** = the COT direction also earns at least 0.5% carry. **Grade B** = carry too small or against you (not traded by default) |
| Small moves against the trend on the COT line are smart money hedging | The side of the zero line decides, not weekly wiggles; the report marks hedging weeks |
| Then analyse the chart for a market structure break | The EA marks swing highs/lows (HH, HL, LH, LL) and trades the **MSB**: the first close beyond the last swing *against* the trend, in the bias direction |
| Sell it when high / buy low | Stop beyond the high (or low) of the breaking leg, target 2× the risk. A "wait for the retracement" limit entry exists but tested worse (below) |

## Read this before trading: what 26 years of history say

`fxbot backtest` replays every weekly COT report since 2000 (1,396 weeks) against daily closes of all 28 pairs.

**1. The fundamental bias alone does not predict direction.** Over the next 1 or 4 weeks, pairs moved the bot's way ~50% of the time (t-stat 0.4, where ~2 would mean a real edge). Every other reading of the COT data I tried (26-week average, COT-index extremes, with or against large speculators) was also indistinguishable from chance. The reason shows in the data: commercials are net long *after* their currency has fallen (correlation −0.6), so "above zero" is a bet that the fall reverses. That bet alone doesn't pay.

**2. Combined with the market structure break, it does show a small edge.** Entering at the close of the MSB candle in the bias direction:

| | trades | per year | win rate | avg per trade | profit factor | worst drawdown |
|---|---|---|---|---|---|---|
| **EA defaults** (MSB, grade A, enter at the break, 2R target) | 432 | 16 | 41% | **+0.15R** | 1.25 | 29R |
| Same MSB entries without your COT/rates filter | 3,280 | 122 | 35% | +0.05R | 1.08 | 65R |
| "Sell it when high": limit at 50% of the leg | 241 | 9 | 32% | −0.08R | 0.88 | 39R |

- Your filter triples the average trade (+0.05R → +0.15R), with an eighth of the trades and half the drawdown. That is the idea on your page: fundamentals give the direction, structure gives the timing.
- It held in both halves of history (2000–2012: +0.11R, 2013–2026: +0.18R), in every nearby setting tried (+0.05R to +0.17R), and with doubled trading costs (+0.13R).
- The limit entry loses because fills come mostly from breaks that fail: good trades run away without you, bad ones come back and fill you.

**3. It is still modest and not proven.** +0.15R × 16 trades ≈ 2.4R a year, with a 29R worst drawdown and losing years (2008: −17R). The t-stat is 2.2, which is borderline, and about 15 variants were tried, so part of it may be luck. These tests use daily closes only (no intraday wicks) and ignore swaps. Treat it as *promising*: confirm it in MT5's Strategy Tester on FBS data, then on a demo account, before real money.

**Money:** stops sit beyond daily swings, a median of ~190 pips. With FBS's 0.01-lot minimum, risking 0.5% per trade needs roughly **$3,800** on a standard account (1% needs ~$1,900); below that the EA skips trades rather than over-risk. Up to 10 trades were open at once historically.

## Setup (already done on this machine)

```bash
sudo apt install wine                          # 1. Wine (MT5 runs inside it)
scripts/install_mt5.sh                         # 2. MetaTrader 5 in ~/.mt5
uv venv .venv && uv pip install -e ".[dev]"    # 3. Python side
.venv/bin/fxbot export                         # 4. first bias files
scripts/install_ea.sh                          # 5. copy + compile the EA (0 errors, 0 warnings)
scripts/install_timer.sh                       # 6. refresh the bias every 6 hours
```

## Connect FBS and start the EA

1. **Use an MT5 account.** The EA is MQL5, so it will not run on MT4. If your FBS account is MT4, open an MT5 account in the FBS personal area (a demo first).
2. Open **MetaTrader 5** from your app menu (or `WINEPREFIX=~/.mt5 wine ~/.mt5/drive_c/Program\ Files/MetaTrader\ 5/terminal64.exe`).
3. **File → Login to Trade Account**. If FBS's server is not listed, use **File → Open an Account**, type `FBS`, pick FBS, then "Connect with an existing trade account". Tick *Save password*.
4. Open **one** chart, e.g. EURUSD, **D1**. The EA trades all 28 pairs from this single chart; don't attach it to several charts.
5. **Navigator → Expert Advisors → FxBot → FxBot**, drag it onto the chart. On the *Common* tab tick **Allow Algo Trading**. Check the inputs, then OK.
6. Make sure the **Algo Trading** button in the toolbar is green.
7. The top-left of the chart shows the dashboard: bias per pair, trend, last break, open trades. The chart itself gets HH/HL/LH/LL labels and dashed MSB/BOS lines, like your diagram.
8. If a symbol is "not found", your account uses suffixed names (e.g. `EURUSD.a`). Set **InpSymbolSuffix**.

## Every week

- `fxbot report`: this week's picture (currencies, COT sides, pairs in play). The COT lands Fridays around 22:30–23:30 EAT; the timer picks it up.
- **Give the bot your own read** (e.g. from Barchart or news). Your call beats the bot's:
  - in `config.yaml` → `overrides: {USDCHF: SELL}` then `fxbot export` (shows as grade M), or
  - in the EA's input **InpManualBias**: `USDCHF=SELL,EURUSD=NEUTRAL`.
- **Rates**: keep updating your Forex Chart page as you do now, and the bot reads its table. If a central bank moves before you update it, pin the rate under `rates.manual` in `config.yaml`.

## Backtest in MT5 on FBS data (do this before going live)

```bash
.venv/bin/fxbot export              # makes sure the bias history file is current
scripts/mt5_backtest.sh 2016.01.01  # MT5 must be closed; runs the Strategy Tester and prints the headline numbers
PERIOD=H4 scripts/mt5_backtest.sh   # try the 4-hour chart (untested in Python)
```

The tester reads `fxbot_bias_history.csv`, so each simulated week sees only the bias known at the time.

Also useful: `fxbot backtest --help` for the Python research runs (`--no-bias`, `--retrace 0.5`, `--bos`, `--grade-b`, `--rr 3` …).

## Keeping it running

- Stops and targets sit on FBS's server, so open trades stay protected even when your PC is off.
- New entries and bias-flip exits need MT5 running. The EA catches up on the last closed candle when it restarts.
- Laptop asleep over Friday night? The timer runs the missed refresh on wake. The EA stops opening trades if the bias is more than 10 days old (the dashboard says "stale").
- For 24/5 without your PC: a small Linux VPS with this same setup (Wine + MT5 + fxbot).

## EA inputs

| Input | Default | Meaning |
|---|---|---|
| InpManualBias | *(empty)* | Your calls, `PAIR=BUY/SELL/NEUTRAL`, comma separated |
| InpAllowGradeB | false | Also trade against the carry |
| InpTimeframe | D1 | Chart timeframe for structure (tested on D1) |
| InpSwingStrength | 3 | Candles each side of a swing point |
| InpBreaks | MSB only | Add BOS (continuation breaks) if you like; tested worse |
| InpEntryRetrace | 0 | 0 = enter at the break; 0.5 = "sell it when high" limit entry |
| InpRewardRisk | 2.0 | Target in R |
| InpExitOnBiasFlip | true | Close when the weekly bias turns against the trade |
| InpRiskPercent | 0.5 | % of equity risked per trade |
| InpMaxTrades | 8 | Open trades + pending orders across all pairs |
| InpMaxDailyLossPct | 3 | Stop opening trades after this daily loss |
| InpMaxSpreadStopPct | 5 | Waits out rollover spreads (D1 candles close at rollover) |
| InpSymbolSuffix | *(empty)* | Broker symbol suffix |

## Files

```
fxbot/          Python: cot.py (CFTC), rates.py (your site + BIS), bias.py (your rules),
                structure.py (swings/MSB - twin of the EA), backtest.py, export.py, cli.py
mt5/FxBot.mq5   the Expert Advisor
scripts/        install_mt5.sh, install_ea.sh, install_timer.sh, mt5_backtest.sh
config.yaml     your settings and overrides
tests/          pytest suite (.venv/bin/python -m pytest)
trade.py        older Quotex experiment; not used by FxBot
```

Data sources, all free and keyless: CFTC Public Reporting (COT), your Forex Chart page (today's rates), Bank for International Settlements (rate history), FRED (daily closes for research).

Trading leveraged FX can lose more than you expect. Nothing here is a promise of profit. Test on demo first.
