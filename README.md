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

## Read this before trading: the backtests say it does not make money yet

**On FBS's own data** (MT5 Strategy Tester, 2016-01-01 to 2026-09-24, daily chart, 1-minute OHLC, 98% history quality, $10,000 at 0.5% risk):

| trades | win rate | net profit | profit factor | avg per trade | max drawdown |
|---|---|---|---|---|---|
| 116 | 30% | **−$408 (−4.1%)** | 0.86 | −0.13R | 11.2% |

Real stops fire on intraday wicks and swings form on wicks too, so the trades differ from a closing-price test: of the Python winners that also traded in MT5, about a third were stopped out by a wick first. Swaps were small (+$95 over ten years).

**Python research** (`fxbot backtest`, FRED daily closes, every weekly COT report since 2000, all 28 pairs):

1. **The fundamental bias alone does not predict direction.** Over the next 1 or 4 weeks pairs moved the bot's way ~50% of the time (t-stat 0.4, where ~2 would mean a real edge). Every other reading of the COT data tried (26-week average, COT-index extremes, with or against large speculators) was also chance-level. Commercials are net long *after* their currency has fallen (correlation −0.6), so "above zero" is a bet that the fall reverses, and on its own that bet doesn't pay.
2. **With the market structure break it is roughly break-even, before real-world wicks:**

| | trades | win rate | avg per trade | profit factor | worst drawdown |
|---|---|---|---|---|---|
| EA defaults (MSB, grade A, enter at the break, 2R) | 432 | 41% | −0.03R | 0.97 | 51R |
| Same MSB entries without your COT/rates filter | 3,280 | 35% | −0.11R | 0.86 | 395R |
| "Sell it when high": limit at 50% of the leg | 241 | 32% | −0.55R | 0.53 | 143R |

- Your filter does carry information: it turns −0.11R into −0.03R per trade. It is not enough to beat the costs of trading.
- The limit entry is worst because fills come mostly from breaks that fail: good trades run away without you, bad ones come back and fill you.
- An earlier version of this backtest reported +0.15R per trade. It checked stops only at the daily close but filled them at the stop price, which is too kind; the MT5 run exposed it and it is fixed.

**What this means:** don't fund a real account expecting this to make money. Run it on demo, or use it to test changes to the idea, and judge any change by an MT5 run on FBS data covering years you didn't tune it on.

**Money:** stops sit beyond daily swings, a median of ~190 pips. With FBS's 0.01-lot minimum, risking 0.5% per trade needs roughly **$3,800** on a standard account (1% needs ~$1,900); below that the EA skips trades rather than over-risk. Up to 10 trades were open at once historically.

## Strategy lab: what else was tested

`fxbot lab` runs textbook strategies with their standard settings (fixed before looking at results) on long free histories, after retail costs:

| Market | Strategy | Sharpe after costs | Sharpe 2015–2026 | Verdict |
|---|---|---|---|---|
| Forex, dollar pairs 1975–2026 | trend (12-month momentum) | 0.39 | −0.14 | worked until ~2004, not since |
| | carry + trend filter | 0.61 | −0.26 | same story |
| Forex, all 28 pairs 2000–2026 | best of six (carry) | 0.24 (t 1.25) | – | not reliable |
| NASDAQ 100 (US100 CFD), 1986–2026 | hold only above the 200-day average | 0.45 | 0.70 | held up in every decade since 1995 |
| | RSI-2 dip-buying in an uptrend | 0.41 | 0.50 | held up since 1995, in the market 12% of the time |
| | buy and hold (benchmark) | 0.42 | 0.66 | – |

Caveats: the NASDAQ was the best-performing index of this era, so choosing it is partly hindsight; CFD financing is assumed at the Fed funds rate + 2.5%/yr (FBS's real US100 swap turned out to be ~4%/yr); drawdowns were still 40–65%.

## Your strategy as a day trade (London open → New York midday)

`fxbot intraday` tests the COT/rates bias with 15-minute market structure breaks, trading only from 08:00 London (10:00 server) to 12:00 New York (19:00 server), on FBS's own 15-minute bars 2010–2026 with FBS's recorded spreads + 0.3 pips slippage:

| | trades | win rate | avg per trade | t-stat | total |
|---|---|---|---|---|---|
| Bias only: open at London, close at midday | 10,541 | 49.5% | −0.7 pips | −1.3 | – |
| **Your strategy intraday (bias + 15-min MSB, 2R)** | 6,859 | 42% | **−0.05R** | −4.5 | −356R |
| Same entries without the bias | 118,356 | 39% | −0.10R | −34.7 | −11,835R |

Before costs it has a tiny edge (+0.03R per trade, t +2.2), but FBS's spreads (0.8 pips on EURUSD up to 6 pips on GBPCAD) plus slippage cost ~0.08R per trade on the typical 29-pip stop. A 1R target or a plain midday exit lose the same. It lost in 15 of 17 years. Intraday trading makes costs a much bigger share of each trade.

Reproduce: export the bars once (`EA=ExportBars SYMBOL=EURUSD PERIOD=M15 MODEL=2 scripts/mt5_backtest.sh 2010.01.01`, MT5 closed), then `.venv/bin/fxbot intraday`.

## IndexBot: NASDAQ 100 (`US100`)

`mt5/IndexBot.mq5` trades the two index rules that held up, on daily candles, acting once a day at **22:45 server time** (just before the US close) with that price as the day's close:

- **Trend** (0.5× equity): hold US100 while it closes above its 200-day average.
- **Dip** (0.5× equity): buy when the 2-day RSI closes below 10 while above the 200-day average; sell on a close above the 5-day average.

| | Python, 1986–2026 (NASDAQ 100, CFD costs) | MT5 on FBS data, 2020-05 → 2026-09 |
|---|---|---|
| **Both (default)** | Sharpe 0.51, ~5.6%/yr, worst drawdown 38% | **+107%**, worst drawdown 13%, 65 trades |
| Trend only (1×) | Sharpe 0.45, ~6.7%/yr, worst drawdown 65% | +196%, worst drawdown 17%, 8 trades |
| Dip only (1×) | Sharpe 0.41, ~3.7%/yr, worst drawdown 40% | +36%, worst drawdown 10%, 57 trades |
| Buy and hold (1×) | Sharpe 0.42 | same window in Python: +151%, worst drawdown 38% |

- Python and MT5 agree on the same window (both rules: +104% vs +107%, drawdown 13.6% vs 13.0%), so the EA trades the rules as tested.
- FBS only has minute data for US100 from May 2020, so MT5 cannot test earlier years; the long Python history covers them.
- 2020–2026 was an unusually strong NASDAQ run. Expect something closer to the 40-year numbers.
- FBS charges about 4%/yr of the position's value to hold US100 long overnight; the MT5 numbers include it.
- **Size:** 1 lot = $10 per point, so the smallest trade (0.01 lot) is worth ~$3,000 at today's prices. The default (0.5× per rule) needs ~$6,000 of equity; below that it skips trades rather than borrow more.
- **Timing:** MT5 must be running at 22:45 server time (22:45 Kenya time from late March to late October, 23:45 in winter).

### IndexBot stress tests (`fxbot indexlab`)

| Test | Result |
|---|---|
| EA vs the rules, trade by trade (FBS, 2020–2026) | 93% (trend) and 90% (dip) of orders on the same day and side; the rest fall on days missing from the exported 15-minute data |
| 27 nearby settings (150/200/250-day, RSI 5/10/15, 3/5/10-day exit), NASDAQ 100 1986–2026 | Sharpe 0.49 to 0.62, default 0.56: not a lucky setting |
| Higher costs (FBS swap is ~4%/yr) | swap 2%: 0.63 · 4%: 0.56 · 6%: 0.49 · 8%: 0.42; spreads barely matter |
| 2,000 ten-year histories (one-year blocks of 1986–2026) | median 6.3%/yr (worst 5%: 0.1%/yr), median worst drawdown 22% (worst 5%: 36%), 4% chance of a losing decade (holding the index: 13%) |
| MT5 off at 22:45 on 10–30% of days | no real change; at 50% of days, Sharpe 0.56 → 0.49 |
| **Same rules on FBS's other indices, 2013–2026** | beats holding only on the NASDAQ (US100 Sharpe 0.74 vs 0.69, with a third of the drawdown); about equal on US500; worse than holding on US30, DE30, JP225, EU50, FR40, ES35; loses on UK100 and HK50. The dip rule alone was positive on 8 of 10 indices. |

**Verdict:** the EA trades the rules exactly and the settings are not a fluke, but the profit comes from the NASDAQ's long uptrend. It is a smoother way to hold the NASDAQ (similar long-run return, about half the drawdown), not something that makes money in any market. Use it on US100 only.

Run it: open a US100 chart, drag **IndexBot** onto it, tick *Allow Algo Trading*. Backtest: `EA=IndexBot SYMBOL=US100 scripts/mt5_backtest.sh 2020.06.01` (MT5 closed first).

## MarketStructure indicator (chart tool, never trades)

`mt5/indicators/MarketStructure.mq5` draws your strategy on any chart, for trading by hand:

- **Swing labels:** first `H`/`L` in grey, then `HH`, `HL` in green (bullish structure) and `LH`, `LL` in red (bearish).
- **Breaks:** a dashed line from the broken swing to the candle that closed through it, labelled **MSB** (first break against the trend: your market structure break) or **BOS** (break in the trend's direction).
- **Panel** (bottom-left): the trend on this timeframe and on a higher one (daily by default), the pair's weekly **COT + interest-rate bias** (BUY/SELL, grade, carry, which currency is bullish or bearish, COT report date) and whether the structure agrees with the bias. The bias covers the 28 currency pairs; it comes from `fxbot export`, which the 6-hourly timer keeps fresh.
- **Alerts** (off by default): a pop-up and/or a push to the MetaTrader phone app when an MSB appears, by default only when it matches the bias.
- Nothing repaints: a swing label appears once 3 candles have closed after it, a break only when a candle closes through the level.

Add it: Navigator → **Indicators → MarketStructure** → drag onto a chart. To have it on every new chart, right-click the chart → **Templates → Save Template** → `default`.

The same signals traded mechanically did not beat FBS's costs (see the backtests above), so any edge has to come from your judgment: log every trade and prove it on demo first.

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
fxbot/lab.py    strategy lab (`fxbot lab`): trend, carry, COT and index rules on long history
mt5/FxBot.mq5   the forex EA (COT + interest rates + market structure)
mt5/IndexBot.mq5  the NASDAQ 100 EA (200-day trend + RSI-2 dips)
scripts/        install_mt5.sh, install_ea.sh (compiles every EA), install_timer.sh, mt5_backtest.sh
config.yaml     your settings and overrides
tests/          pytest suite (.venv/bin/python -m pytest)
trade.py        older Quotex experiment; not used by FxBot
```

Data sources, all free and keyless: CFTC Public Reporting (COT), your Forex Chart page (today's rates), Bank for International Settlements (rate history), FRED (daily closes for research).

Trading leveraged FX can lose more than you expect. Nothing here is a promise of profit. Test on demo first.
