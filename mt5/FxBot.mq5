//+------------------------------------------------------------------+
//|                                                        FxBot.mq5 |
//|  Trades the weekly fundamental bias written by `fxbot export`    |
//|  (interest-rate differential + COT commercials) when price       |
//|  breaks market structure in the same direction.                  |
//|                                                                  |
//|  The structure logic mirrors fxbot/structure.py - keep them      |
//|  in step so backtests in Python and MT5 agree.                   |
//+------------------------------------------------------------------+
#property copyright   "Chebon Kibet"
#property link        "https://forexchart-kibet.web.app"
#property version     "1.00"
#property description "Weekly bias from fxbot (interest differential + COT commercials),"
#property description "entered on a market structure break in the same direction."

#include <Trade\Trade.mqh>

#define FXBOT_VERSION "1.00"
#define FXBOT_PREFIX  "FxBot_"

enum ENUM_BREAKS
  {
   BREAKS_MSB_ONLY = 0, // MSB only (first break against the trend)
   BREAKS_MSB_BOS  = 1  // MSB and BOS (continuation breaks too)
  };

input group "Bias (fundamentals from fxbot)"
input bool   InpUseBiasFile      = true;                     // Use the bias file written by `fxbot export`
input string InpBiasFile         = "fxbot_bias.csv";         // Live bias file (in MT5 Common\Files)
input string InpBiasHistoryFile  = "fxbot_bias_history.csv"; // Bias history (used in the Strategy Tester)
input string InpManualBias       = "";                       // Your own calls, e.g. AUDJPY=BUY,USDCHF=SELL
input bool   InpAllowGradeB      = false;                    // Also trade grade B (carry small or against you)
input int    InpMaxBiasAgeDays   = 10;                       // No new trades when the bias is older than this

input group "Market structure (technicals)"
input ENUM_TIMEFRAMES InpTimeframe     = PERIOD_D1;          // Structure timeframe
input int             InpSwingStrength = 3;                  // Bars each side of a swing point
input ENUM_BREAKS     InpBreaks        = BREAKS_MSB_ONLY;    // Which breaks open trades
input int             InpLookbackBars  = 300;                // Bars scanned for structure

input group "Entries and exits"
input double InpEntryRetrace     = 0.0;  // 0 = enter at the break; 0.5 = limit at 50% of the break leg
input int    InpOrderExpiryBars  = 10;   // Cancel unfilled limit orders after this many bars
input int    InpSignalValidHours = 8;    // Market entries: keep trying this long while spreads are wide
input double InpRewardRisk       = 2.0;  // Take profit in multiples of the risk (R)
input double InpStopBufferATR    = 0.1;  // Extra room beyond the swing for the stop, in ATR(14)
input bool   InpExitOnBiasFlip   = true; // Close a trade when the weekly bias turns against it

input group "Risk"
input double InpRiskPercent      = 0.5;  // Risk per trade, % of equity
input int    InpMaxTrades        = 8;    // Max open positions + pending orders (all pairs)
input double InpMaxDailyLossPct  = 3.0;  // No new trades after losing this % in a day (0 = off)
input double InpMaxSpreadStopPct = 5.0;  // Wait while the spread is above this % of the stop distance

input group "Symbols"
input string InpSymbols = "EURUSD,GBPUSD,AUDUSD,NZDUSD,USDCAD,USDCHF,USDJPY,EURGBP,EURAUD,EURNZD,EURCAD,EURCHF,EURJPY,GBPAUD,GBPNZD,GBPCAD,GBPCHF,GBPJPY,AUDNZD,AUDCAD,AUDCHF,AUDJPY,NZDCAD,NZDCHF,NZDJPY,CADCHF,CADJPY,CHFJPY"; // Pairs to trade
input string InpSymbolSuffix  = "";       // Broker suffix added to each pair (blank on most FBS accounts)
input long   InpMagic         = 26092401; // Magic number that tags this EA's trades
input bool   InpDrawStructure = true;     // Draw swings and breaks on this chart

//+------------------------------------------------------------------+
struct SwingPoint
  {
   int               bar;
   double            price;
   bool              isHigh;
  };

struct BreakEvent
  {
   int               bar;       // bar whose close broke the swing
   int               dir;       // +1 broke a high, -1 broke a low
   bool              isMSB;     // against the trend (MSB) or with it (BOS)
   double            level;     // price of the broken swing
   int               swingBar;
   double            rangeHigh; // the leg that made the break
   double            rangeLow;
  };

//+------------------------------------------------------------------+
//| One tradable pair: its weekly bias rows and working state        |
//+------------------------------------------------------------------+
class CMarket
  {
public:
   string            pair;
   string            symbol;
   bool              ok;
   datetime          lastBar;
   int               trend;
   string            lastBreak;
   datetime          biasTime[];
   int               biasDir[];
   string            biasGrade[];
   double            biasCarry[];
   int               cursor;
   // a market entry waiting for a normal spread
   int               sigDir;
   double            sigSL;
   double            sigTP;
   datetime          sigExpires;
   datetime          sigNextTry;
   string            sigComment;
   bool              sigWarned;

                     CMarket(void) : ok(false), lastBar(0), trend(0), lastBreak("-"), cursor(-1),
                     sigDir(0), sigSL(0), sigTP(0), sigExpires(0), sigNextTry(0), sigComment(""), sigWarned(false) {}

   void              ClearBias(void)
     {
      ArrayResize(biasTime, 0);
      ArrayResize(biasDir, 0);
      ArrayResize(biasGrade, 0);
      ArrayResize(biasCarry, 0);
      cursor = -1;
     }

   void              AddBias(const datetime t, const int dir, const string grade, const double carry)
     {
      int k = ArraySize(biasTime);
      ArrayResize(biasTime, k + 1, 1024);
      ArrayResize(biasDir, k + 1, 1024);
      ArrayResize(biasGrade, k + 1, 1024);
      ArrayResize(biasCarry, k + 1, 1024);
      biasTime[k]  = t;
      biasDir[k]   = dir;
      biasGrade[k] = grade;
      biasCarry[k] = carry;
     }

   //--- newest row in force at `now` (-1 if none). Rows are oldest first.
   int               BiasIndex(const datetime now)
     {
      int n = ArraySize(biasTime);
      if(cursor >= n || (cursor >= 0 && biasTime[cursor] > now))
         cursor = -1;
      while(cursor + 1 < n && biasTime[cursor + 1] <= now)
         cursor++;
      return cursor;
     }
  };

CMarket *g_markets[];
CTrade   g_trade;
string   g_manualPair[];
int      g_manualDir[];
datetime g_biasFileTime   = 0;
datetime g_biasNewest     = 0;
string   g_biasStatus     = "not loaded";
int      g_day            = -1;
double   g_dayStartEquity = 0;
bool     g_tester         = false;
datetime g_lastScan       = 0;

//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpRiskPercent <= 0 || InpRiskPercent > 5)
     {
      Print("InpRiskPercent must be above 0 and at most 5");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(InpEntryRetrace < 0 || InpEntryRetrace >= 1 || InpSwingStrength < 1 || InpRewardRisk <= 0 || InpLookbackBars < 50)
     {
      Print("Check the inputs: retrace 0 to 0.99, swing strength 1+, reward/risk above 0, lookback 50+");
      return INIT_PARAMETERS_INCORRECT;
     }
   g_tester = (bool)MQLInfoInteger(MQL_TESTER);
   g_lastScan = 0;
   g_trade.SetExpertMagicNumber((ulong)InpMagic);
   g_trade.SetDeviationInPoints(30);
   BuildMarkets();
   ParseManualBias();
   if(InpUseBiasFile)
      LoadBias();
   EventSetTimer(30);
   UpdateDay();
   Scan();
   UpdateDashboard();
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   for(int i = 0; i < ArraySize(g_markets); i++)
      delete g_markets[i];
   ArrayResize(g_markets, 0);
   ObjectsDeleteAll(0, FXBOT_PREFIX);
   Comment("");
  }

void OnTick()
  {
   Scan();
  }

void OnTimer()
  {
   if(InpUseBiasFile && !g_tester)
     {
      long modified = FileGetInteger(BiasFileName(), FILE_MODIFY_DATE, true);
      if(modified > 0 && (datetime)modified != g_biasFileTime)
         LoadBias();
     }
   Scan();
   UpdateDashboard();
  }

//+------------------------------------------------------------------+
void Scan()
  {
   // Once a minute is plenty for D1/H4 decisions, and keeps the Strategy Tester fast.
   datetime now = TimeCurrent();
   if(now - g_lastScan < 60)
      return;
   g_lastScan = now;
   UpdateDay();
   for(int i = 0; i < ArraySize(g_markets); i++)
     {
      CMarket *m = g_markets[i];
      if(!m.ok)
         continue;
      ProcessNewBar(m);
      TrySignal(m);
     }
  }

//+------------------------------------------------------------------+
//| Everything that happens once per closed bar on one pair          |
//+------------------------------------------------------------------+
void ProcessNewBar(CMarket *m)
  {
   datetime closed = iTime(m.symbol, InpTimeframe, 1);
   if(closed == 0 || closed == m.lastBar)
      return;
   MqlRates r[];
   int n = CopyRates(m.symbol, InpTimeframe, 1, InpLookbackBars, r);
   if(n < 2 * InpSwingStrength + 20 || r[n - 1].time != closed)
      return; // history still loading - try again on the next tick
   m.lastBar = closed;

   SwingPoint swings[];
   BreakEvent breaks[];
   int trend = 0;
   AnalyzeStructure(r, n, InpSwingStrength, swings, breaks, trend);
   m.trend = trend;
   int nb = ArraySize(breaks);
   if(nb > 0)
      m.lastBreak = StringFormat("%s %s %s", breaks[nb - 1].isMSB ? "MSB" : "BOS",
                                 breaks[nb - 1].dir > 0 ? "up" : "down",
                                 TimeToString(r[breaks[nb - 1].bar].time, TIME_DATE));

   int dir = 0;
   string grade = "-";
   double carry = 0;
   bool stale = true;
   bool have = GetBias(m, TimeCurrent(), dir, grade, carry, stale);
   bool gradeOk = (grade == "A" || grade == "M" || (InpAllowGradeB && grade == "B"));
   int want = (have && !stale && gradeOk) ? dir : 0;

   // 1. the weekly bias turned against an open trade
   if(InpExitOnBiasFlip && have && !stale && dir != 0)
      ClosePositions(m.symbol, -dir);
   // 2. waiting orders/entries the bias no longer supports, or limit orders that waited too long
   ManagePendingOrders(m, want);
   if(m.sigDir != 0 && m.sigDir != want)
      m.sigDir = 0;
   // 3. a break on the bar that just closed, in the bias direction
   for(int i = 0; i < nb; i++)
     {
      if(breaks[i].bar != n - 1 || want == 0 || breaks[i].dir != want)
         continue;
      if(InpBreaks == BREAKS_MSB_ONLY && !breaks[i].isMSB)
         continue;
      if(HasPosition(m.symbol))
         continue;
      Setup(m, breaks[i], r, n, grade);
     }

   if(InpDrawStructure && m.symbol == _Symbol && (!g_tester || MQLInfoInteger(MQL_VISUAL_MODE)))
      DrawStructure(r, n, swings, breaks);
  }

//+------------------------------------------------------------------+
//| Market structure - the twin of fxbot/structure.py                |
//+------------------------------------------------------------------+
void AnalyzeStructure(const MqlRates &r[], const int n, const int strength,
                      SwingPoint &swings[], BreakEvent &breaks[], int &trend)
  {
   ArrayResize(swings, 0);
   ArrayResize(breaks, 0);
   trend = 0;
   double hiPrice = 0, loPrice = 0;
   int    hiBar = -1, loBar = -1;
   bool   hiBroken = true, loBroken = true;

   for(int t = 0; t < n; t++)
     {
      int i = t - strength;
      if(i >= strength)
        {
         if(IsSwingHigh(r, i, strength))
           {
            hiPrice  = r[i].high;
            hiBar    = i;
            hiBroken = false;
            PushSwing(swings, i, r[i].high, true);
           }
         if(IsSwingLow(r, i, strength))
           {
            loPrice  = r[i].low;
            loBar    = i;
            loBroken = false;
            PushSwing(swings, i, r[i].low, false);
           }
        }

      if(hiBar >= 0 && !hiBroken && r[t].close > hiPrice)
        {
         hiBroken = true;
         int start = hiBar; // the low the rally started from
         for(int k = hiBar + 1; k <= t; k++)
            if(r[k].low < r[start].low)
               start = k;
         double top = r[start].high;
         for(int k = start + 1; k <= t; k++)
            if(r[k].high > top)
               top = r[k].high;
         PushBreak(breaks, t, 1, trend != 1, hiPrice, hiBar, top, r[start].low);
         trend = 1;
        }

      if(loBar >= 0 && !loBroken && r[t].close < loPrice)
        {
         loBroken = true;
         int start = loBar; // the high the drop started from
         for(int k = loBar + 1; k <= t; k++)
            if(r[k].high > r[start].high)
               start = k;
         double bottom = r[start].low;
         for(int k = start + 1; k <= t; k++)
            if(r[k].low < bottom)
               bottom = r[k].low;
         PushBreak(breaks, t, -1, trend != -1, loPrice, loBar, r[start].high, bottom);
         trend = -1;
        }
     }
  }

//--- strictly above the `s` bars before, at least as high as the `s` bars after
bool IsSwingHigh(const MqlRates &r[], const int i, const int s)
  {
   for(int k = i - s; k < i; k++)
      if(r[k].high >= r[i].high)
         return false;
   for(int k = i + 1; k <= i + s; k++)
      if(r[k].high > r[i].high)
         return false;
   return true;
  }

bool IsSwingLow(const MqlRates &r[], const int i, const int s)
  {
   for(int k = i - s; k < i; k++)
      if(r[k].low <= r[i].low)
         return false;
   for(int k = i + 1; k <= i + s; k++)
      if(r[k].low < r[i].low)
         return false;
   return true;
  }

void PushSwing(SwingPoint &arr[], const int bar, const double price, const bool isHigh)
  {
   int k = ArraySize(arr);
   ArrayResize(arr, k + 1, 64);
   arr[k].bar    = bar;
   arr[k].price  = price;
   arr[k].isHigh = isHigh;
  }

void PushBreak(BreakEvent &arr[], const int bar, const int dir, const bool isMSB, const double level,
               const int swingBar, const double rangeHigh, const double rangeLow)
  {
   int k = ArraySize(arr);
   ArrayResize(arr, k + 1, 32);
   arr[k].bar       = bar;
   arr[k].dir       = dir;
   arr[k].isMSB     = isMSB;
   arr[k].level     = level;
   arr[k].swingBar  = swingBar;
   arr[k].rangeHigh = rangeHigh;
   arr[k].rangeLow  = rangeLow;
  }

double AverageTrueRange(const MqlRates &r[], const int n, const int period)
  {
   if(n <= period)
      return 0;
   double sum = 0;
   for(int k = n - period; k < n; k++)
      sum += MathMax(r[k].high, r[k - 1].close) - MathMin(r[k].low, r[k - 1].close);
   return sum / period;
  }

//+------------------------------------------------------------------+
//| Turning a break into an order                                    |
//+------------------------------------------------------------------+
void Setup(CMarket *m, const BreakEvent &e, const MqlRates &r[], const int n, const string grade)
  {
   double buffer = InpStopBufferATR * AverageTrueRange(r, n, 14);
   double span   = e.rangeHigh - e.rangeLow;
   double last   = r[n - 1].close;
   double entry, sl, tp;
   if(e.dir < 0)
     {
      entry = InpEntryRetrace > 0 ? e.rangeLow + InpEntryRetrace * span : last;
      sl    = e.rangeHigh + buffer;
      tp    = entry - InpRewardRisk * (sl - entry);
     }
   else
     {
      entry = InpEntryRetrace > 0 ? e.rangeHigh - InpEntryRetrace * span : last;
      sl    = e.rangeLow - buffer;
      tp    = entry + InpRewardRisk * (entry - sl);
     }
   if(MathAbs(entry - sl) < 10 * SymbolInfoDouble(m.symbol, SYMBOL_POINT))
      return;
   // after a terminal restart the same bar is seen again: act on each break only once
   if(EnteredSince(m.symbol, r[n - 1].time + PeriodSeconds(InpTimeframe)))
      return;
   string comment = StringFormat("FxBot %s %s", e.isMSB ? "MSB" : "BOS", grade);
   DeletePendingOrders(m.symbol); // a newer setup replaces an older one
   m.sigDir = 0;
   if(InpEntryRetrace > 0)
      PlaceLimit(m, e.dir, entry, sl, tp, comment);
   else
      QueueSignal(m, e.dir, sl, tp, comment);
  }

//--- market entries wait here until the spread is reasonable (D1 bars close at rollover)
void QueueSignal(CMarket *m, const int dir, const double sl, const double tp, const string comment)
  {
   m.sigDir     = dir;
   m.sigSL      = NormalizePrice(m.symbol, sl);
   m.sigTP      = NormalizePrice(m.symbol, tp);
   m.sigExpires = TimeCurrent() + InpSignalValidHours * 3600;
   m.sigNextTry = 0;
   m.sigComment = comment;
   m.sigWarned  = false;
   TrySignal(m);
  }

void TrySignal(CMarket *m)
  {
   if(m.sigDir == 0 || TimeCurrent() < m.sigNextTry)
      return;
   string sym = m.symbol;
   if(HasPosition(sym))
     {
      m.sigDir = 0;
      return;
     }
   if(TimeCurrent() > m.sigExpires)
     {
      PrintFormat("%s: entry dropped - spread stayed too wide for %d hours", sym, InpSignalValidHours);
      m.sigDir = 0;
      return;
     }
   double bid = SymbolInfoDouble(sym, SYMBOL_BID);
   double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
   if(bid <= 0 || ask <= 0)
      return;
   double price = m.sigDir > 0 ? ask : bid;
   if((m.sigDir > 0 && (price <= m.sigSL || price >= m.sigTP)) ||
      (m.sigDir < 0 && (price >= m.sigSL || price <= m.sigTP)))
     {
      PrintFormat("%s: entry dropped - price already reached the stop or target", sym);
      m.sigDir = 0;
      return;
     }
   double minDist = StopsDistance(sym);
   if(MathAbs(price - m.sigSL) <= minDist || MathAbs(m.sigTP - price) <= minDist)
      return;
   if((ask - bid) > MathAbs(price - m.sigSL) * InpMaxSpreadStopPct / 100.0)
      return; // rollover spread - try again on the next tick
   if(!CanOpenNew())
     {
      m.sigDir = 0;
      return;
     }
   double lots = LotsForRisk(sym, m.sigDir > 0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, price, m.sigSL);
   if(lots <= 0)
     {
      m.sigDir = 0;
      return;
     }
   g_trade.SetTypeFillingBySymbol(sym);
   bool sent = m.sigDir > 0 ? g_trade.Buy(lots, sym, price, m.sigSL, m.sigTP, m.sigComment)
               : g_trade.Sell(lots, sym, price, m.sigSL, m.sigTP, m.sigComment);
   uint code = g_trade.ResultRetcode();
   if(!Succeeded(sent, code) && IsTransient(code))
     {
      // e.g. the session opens a few minutes after the daily candle, a requote, or Algo Trading
      // switched off: say so once, then retry every minute until the signal expires
      if(!m.sigWarned)
         PrintFormat("%s: %s not possible yet (%s) - retrying every minute", sym, m.sigDir > 0 ? "buy" : "sell",
                     g_trade.ResultRetcodeDescription());
      m.sigWarned  = true;
      m.sigNextTry = TimeCurrent() + 60;
      return;
     }
   LogResult(sym, sent, m.sigDir > 0 ? "buy" : "sell", lots, price, m.sigSL, m.sigTP);
   m.sigDir = 0;
  }

void PlaceLimit(CMarket *m, const int dir, double entry, double sl, double tp, const string comment)
  {
   string sym = m.symbol;
   entry = NormalizePrice(sym, entry);
   sl    = NormalizePrice(sym, sl);
   tp    = NormalizePrice(sym, tp);
   double bid = SymbolInfoDouble(sym, SYMBOL_BID);
   double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
   double minDist = StopsDistance(sym);
   // price is already through the limit level: take the better price at market
   if((dir < 0 && bid >= entry - minDist) || (dir > 0 && ask <= entry + minDist))
     {
      QueueSignal(m, dir, sl, tp, comment);
      return;
     }
   if(!CanOpenNew())
      return;
   double lots = LotsForRisk(sym, dir > 0 ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, entry, sl);
   if(lots <= 0)
      return;
   g_trade.SetTypeFillingBySymbol(sym);
   bool sent = dir > 0 ? g_trade.BuyLimit(lots, entry, sym, sl, tp, ORDER_TIME_GTC, 0, comment)
               : g_trade.SellLimit(lots, entry, sym, sl, tp, ORDER_TIME_GTC, 0, comment);
   LogResult(sym, sent, dir > 0 ? "buy limit" : "sell limit", lots, entry, sl, tp);
  }

bool Succeeded(const bool sent, const uint code)
  {
   return sent && (code == TRADE_RETCODE_DONE || code == TRADE_RETCODE_PLACED || code == TRADE_RETCODE_DONE_PARTIAL);
  }

bool IsTransient(const uint code)
  {
   return code == TRADE_RETCODE_REQUOTE || code == TRADE_RETCODE_PRICE_CHANGED || code == TRADE_RETCODE_PRICE_OFF ||
          code == TRADE_RETCODE_TIMEOUT || code == TRADE_RETCODE_CONNECTION || code == TRADE_RETCODE_MARKET_CLOSED ||
          code == TRADE_RETCODE_TOO_MANY_REQUESTS || code == TRADE_RETCODE_CLIENT_DISABLES_AT;
  }

void LogResult(const string sym, const bool sent, const string what, const double lots,
               const double price, const double sl, const double tp)
  {
   int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   uint code = g_trade.ResultRetcode();
   if(Succeeded(sent, code))
      PrintFormat("%s: %s %.2f lots at %s, stop %s, target %s", sym, what, lots,
                  DoubleToString(price, digits), DoubleToString(sl, digits), DoubleToString(tp, digits));
   else
      PrintFormat("%s: %s failed - %u %s", sym, what, code, g_trade.ResultRetcodeDescription());
  }

//+------------------------------------------------------------------+
//| Risk                                                             |
//+------------------------------------------------------------------+
double LotsForRisk(const string sym, const ENUM_ORDER_TYPE type, const double price, const double sl)
  {
   double riskMoney = AccountInfoDouble(ACCOUNT_EQUITY) * InpRiskPercent / 100.0;
   double pnl = 0;
   if(!OrderCalcProfit(type, sym, 1.0, price, sl, pnl) || pnl >= 0)
     {
      PrintFormat("%s: could not value the stop (error %d)", sym, GetLastError());
      return 0;
     }
   double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(sym, SYMBOL_VOLUME_MAX);
   if(step <= 0)
      step = vmin;
   double lots = MathFloor(riskMoney / -pnl / step + 1e-9) * step;
   if(lots < vmin)
     {
      PrintFormat("%s: skipped - %.2f%% risk is %.2f %s, but the smallest lot (%.2f) would risk %.2f",
                  sym, InpRiskPercent, riskMoney, AccountInfoString(ACCOUNT_CURRENCY), vmin, -pnl * vmin);
      return 0;
     }
   lots = MathMin(lots, vmax);
   double margin = 0;
   if(OrderCalcMargin(type, sym, lots, price, margin) && margin > AccountInfoDouble(ACCOUNT_MARGIN_FREE))
     {
      PrintFormat("%s: skipped - not enough free margin for %.2f lots", sym, lots);
      return 0;
     }
   return NormalizeDouble(lots, VolumeDigits(step));
  }

int VolumeDigits(const double step)
  {
   int d = 0;
   double s = step;
   while(d < 8 && MathAbs(s - MathRound(s)) > 1e-8)
     {
      s *= 10;
      d++;
     }
   return d;
  }

bool CanOpenNew()
  {
   if(CountOurTrades() >= InpMaxTrades)
     {
      Print("Setup skipped - already at the maximum number of trades");
      return false;
     }
   if(InpMaxDailyLossPct > 0 && AccountInfoDouble(ACCOUNT_EQUITY) < g_dayStartEquity * (1.0 - InpMaxDailyLossPct / 100.0))
     {
      Print("Setup skipped - daily loss limit reached");
      return false;
     }
   return true;
  }

void UpdateDay()
  {
   MqlDateTime t;
   TimeToStruct(TimeCurrent(), t);
   if(t.day_of_year != g_day)
     {
      g_day = t.day_of_year;
      g_dayStartEquity = AccountInfoDouble(ACCOUNT_EQUITY);
     }
  }

double NormalizePrice(const string sym, const double price)
  {
   double tick = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
   if(tick > 0)
      return NormalizeDouble(MathRound(price / tick) * tick, digits);
   return NormalizeDouble(price, digits);
  }

double StopsDistance(const string sym)
  {
   long stops  = SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL);
   long freeze = SymbolInfoInteger(sym, SYMBOL_TRADE_FREEZE_LEVEL);
   return (double)(stops > freeze ? stops : freeze) * SymbolInfoDouble(sym, SYMBOL_POINT);
  }

//+------------------------------------------------------------------+
//| Positions and orders (only this EA's, by magic number)           |
//+------------------------------------------------------------------+
bool HasPosition(const string sym)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(PositionGetTicket(i) > 0 && PositionGetString(POSITION_SYMBOL) == sym && PositionGetInteger(POSITION_MAGIC) == InpMagic)
         return true;
   return false;
  }

void ClosePositions(const string sym, const int dir)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || PositionGetString(POSITION_SYMBOL) != sym || PositionGetInteger(POSITION_MAGIC) != InpMagic)
         continue;
      int posDir = PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY ? 1 : -1;
      if(posDir != dir)
         continue;
      if(g_trade.PositionClose(ticket))
         PrintFormat("%s: closed #%I64u - the weekly bias turned against it", sym, ticket);
      else
         PrintFormat("%s: could not close #%I64u - %s", sym, ticket, g_trade.ResultRetcodeDescription());
     }
  }

int OrderDirection(const long type)
  {
   if(type == ORDER_TYPE_BUY_LIMIT || type == ORDER_TYPE_BUY_STOP)
      return 1;
   if(type == ORDER_TYPE_SELL_LIMIT || type == ORDER_TYPE_SELL_STOP)
      return -1;
   return 0;
  }

void ManagePendingOrders(CMarket *m, const int want)
  {
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0 || OrderGetString(ORDER_SYMBOL) != m.symbol || OrderGetInteger(ORDER_MAGIC) != InpMagic)
         continue;
      int dir = OrderDirection(OrderGetInteger(ORDER_TYPE));
      int age = iBarShift(m.symbol, InpTimeframe, (datetime)OrderGetInteger(ORDER_TIME_SETUP), false);
      string why = "";
      if(dir != want)
         why = "the bias no longer supports it";
      else if(age >= InpOrderExpiryBars)
         why = StringFormat("not filled after %d bars", age);
      if(why != "" && g_trade.OrderDelete(ticket))
         PrintFormat("%s: cancelled order #%I64u - %s", m.symbol, ticket, why);
     }
  }

//--- did this EA already act on a setup on `sym` since `since`? Counts entries and limit orders
//--- (waiting, filled or cancelled) - not exits, so a stop-out or bias-flip close on the same
//--- bar does not block a new trade.
bool EnteredSince(const string sym, const datetime since)
  {
   for(int i = OrdersTotal() - 1; i >= 0; i--)
      if(OrderGetTicket(i) > 0 && OrderGetString(ORDER_SYMBOL) == sym && OrderGetInteger(ORDER_MAGIC) == InpMagic &&
         (datetime)OrderGetInteger(ORDER_TIME_SETUP) >= since)
         return true;
   if(!HistorySelect(since, TimeCurrent() + 86400))
      return false;
   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
     {
      ulong deal = HistoryDealGetTicket(i);
      if(deal > 0 && HistoryDealGetString(deal, DEAL_SYMBOL) == sym && HistoryDealGetInteger(deal, DEAL_MAGIC) == InpMagic &&
         HistoryDealGetInteger(deal, DEAL_ENTRY) == DEAL_ENTRY_IN)
         return true;
     }
   for(int i = HistoryOrdersTotal() - 1; i >= 0; i--)
     {
      ulong ticket = HistoryOrderGetTicket(i);
      if(ticket > 0 && HistoryOrderGetString(ticket, ORDER_SYMBOL) == sym && HistoryOrderGetInteger(ticket, ORDER_MAGIC) == InpMagic &&
         OrderDirection(HistoryOrderGetInteger(ticket, ORDER_TYPE)) != 0)
         return true;
     }
   return false;
  }

void DeletePendingOrders(const string sym)
  {
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong ticket = OrderGetTicket(i);
      if(ticket > 0 && OrderGetString(ORDER_SYMBOL) == sym && OrderGetInteger(ORDER_MAGIC) == InpMagic)
         g_trade.OrderDelete(ticket);
     }
  }

int CountOurTrades()
  {
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(PositionGetTicket(i) > 0 && PositionGetInteger(POSITION_MAGIC) == InpMagic)
         n++;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
      if(OrderGetTicket(i) > 0 && OrderGetInteger(ORDER_MAGIC) == InpMagic)
         n++;
   return n;
  }

//+------------------------------------------------------------------+
//| Bias: manual calls first, then the file from `fxbot export`      |
//+------------------------------------------------------------------+
bool GetBias(CMarket *m, const datetime now, int &dir, string &grade, double &carry, bool &stale)
  {
   for(int i = 0; i < ArraySize(g_manualPair); i++)
      if(g_manualPair[i] == m.pair)
        {
         dir   = g_manualDir[i];
         grade = dir == 0 ? "-" : "M";
         carry = 0;
         stale = false;
         return true;
        }
   if(!InpUseBiasFile)
      return false;
   int k = m.BiasIndex(now);
   if(k < 0)
      return false;
   dir   = m.biasDir[k];
   grade = m.biasGrade[k];
   carry = m.biasCarry[k];
   stale = (now - m.biasTime[k]) > (long)InpMaxBiasAgeDays * 86400;
   return true;
  }

string BiasFileName()
  {
   return g_tester ? InpBiasHistoryFile : InpBiasFile;
  }

//--- CSV from fxbot: symbol,direction,grade,carry,differential,base_side,quote_side,valid_from,valid_from_unix,source
bool LoadBias()
  {
   string name = BiasFileName();
   int h = FileOpen(name, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON | FILE_SHARE_READ | FILE_SHARE_WRITE);
   if(h == INVALID_HANDLE)
     {
      g_biasStatus = name + " not found in Common\\Files - run `fxbot export` on Linux";
      Print(g_biasStatus);
      return false;
     }
   for(int i = 0; i < ArraySize(g_markets); i++)
      g_markets[i].ClearBias();
   int rows = 0;
   datetime newest = 0;
   string report = "?";
   while(!FileIsEnding(h))
     {
      string line = FileReadString(h);
      StringTrimLeft(line);
      StringTrimRight(line);
      if(StringLen(line) == 0)
         continue;
      if(StringGetCharacter(line, 0) == '#')
        {
         int p = StringFind(line, "cot_report ");
         if(p >= 0)
            report = StringSubstr(line, p + 11, 10);
         continue;
        }
      string f[];
      if(StringSplit(line, ',', f) < 9 || f[0] == "symbol")
         continue;
      CMarket *m = FindMarket(f[0]);
      if(m == NULL)
         continue;
      int dir = f[1] == "BUY" ? 1 : (f[1] == "SELL" ? -1 : 0);
      datetime t = (datetime)StringToInteger(f[8]);
      m.AddBias(t, dir, f[2], StringToDouble(f[3]));
      rows++;
      if(t > newest)
         newest = t;
     }
   FileClose(h);
   g_biasFileTime = (datetime)FileGetInteger(name, FILE_MODIFY_DATE, true);
   g_biasNewest   = newest;
   g_biasStatus   = StringFormat("COT report %s, %d rows", report, rows);
   PrintFormat("Bias loaded from %s: %s", name, g_biasStatus);
   return rows > 0;
  }

void ParseManualBias()
  {
   ArrayResize(g_manualPair, 0);
   ArrayResize(g_manualDir, 0);
   string items[];
   int count = StringSplit(InpManualBias, ',', items);
   for(int i = 0; i < count; i++)
     {
      string item = items[i];
      StringTrimLeft(item);
      StringTrimRight(item);
      if(item == "")
         continue;
      string kv[];
      if(StringSplit(item, '=', kv) != 2)
        {
         PrintFormat("Manual bias '%s' ignored - write it as PAIR=BUY, PAIR=SELL or PAIR=NEUTRAL", item);
         continue;
        }
      string pair = kv[0];
      string side = kv[1];
      StringTrimLeft(pair);
      StringTrimRight(pair);
      StringToUpper(pair);
      StringTrimLeft(side);
      StringTrimRight(side);
      StringToUpper(side);
      int dir = 99;
      if(side == "BUY")
         dir = 1;
      else if(side == "SELL")
         dir = -1;
      else if(side == "NEUTRAL")
         dir = 0;
      if(dir == 99 || FindMarket(pair) == NULL)
        {
         PrintFormat("Manual bias '%s' ignored - unknown pair or side", item);
         continue;
        }
      int k = ArraySize(g_manualPair);
      ArrayResize(g_manualPair, k + 1);
      ArrayResize(g_manualDir, k + 1);
      g_manualPair[k] = pair;
      g_manualDir[k]  = dir;
     }
  }

void BuildMarkets()
  {
   string items[];
   int count = StringSplit(InpSymbols, ',', items);
   for(int i = 0; i < count; i++)
     {
      string pair = items[i];
      StringTrimLeft(pair);
      StringTrimRight(pair);
      StringToUpper(pair);
      if(StringLen(pair) != 6 || FindMarket(pair) != NULL)
         continue;
      CMarket *m = new CMarket();
      m.pair   = pair;
      m.symbol = pair + InpSymbolSuffix;
      m.ok     = SymbolSelect(m.symbol, true);
      if(!m.ok)
         PrintFormat("%s is not offered by this broker/account - check InpSymbolSuffix", m.symbol);
      int k = ArraySize(g_markets);
      ArrayResize(g_markets, k + 1);
      g_markets[k] = m;
     }
  }

CMarket *FindMarket(const string pair)
  {
   for(int i = 0; i < ArraySize(g_markets); i++)
      if(g_markets[i].pair == pair)
         return g_markets[i];
   return NULL;
  }

//+------------------------------------------------------------------+
//| Chart output                                                     |
//+------------------------------------------------------------------+
void DrawStructure(const MqlRates &r[], const int n, const SwingPoint &swings[], const BreakEvent &breaks[])
  {
   ObjectsDeleteAll(0, FXBOT_PREFIX);
   int ns = ArraySize(swings);
   int first = MathMax(0, ns - 40);
   double lastHigh = 0, lastLow = 0;
   bool haveHigh = false, haveLow = false;
   for(int i = 0; i < ns; i++)
     {
      string label;
      if(swings[i].isHigh)
        {
         label = !haveHigh ? "H" : (swings[i].price > lastHigh ? "HH" : "LH");
         lastHigh = swings[i].price;
         haveHigh = true;
        }
      else
        {
         label = !haveLow ? "L" : (swings[i].price < lastLow ? "LL" : "HL");
         lastLow = swings[i].price;
         haveLow = true;
        }
      if(i < first)
         continue;
      string name = FXBOT_PREFIX + "sw" + IntegerToString(i);
      ObjectCreate(0, name, OBJ_TEXT, 0, r[swings[i].bar].time, swings[i].price);
      ObjectSetString(0, name, OBJPROP_TEXT, label);
      ObjectSetInteger(0, name, OBJPROP_ANCHOR, swings[i].isHigh ? ANCHOR_LOWER : ANCHOR_UPPER);
      ObjectSetInteger(0, name, OBJPROP_COLOR, clrDodgerBlue);
      ObjectSetInteger(0, name, OBJPROP_FONTSIZE, 8);
     }
   int nb = ArraySize(breaks);
   for(int i = MathMax(0, nb - 15); i < nb; i++)
     {
      color c = breaks[i].dir > 0 ? clrSeaGreen : clrCrimson;
      string name = FXBOT_PREFIX + "brk" + IntegerToString(i);
      ObjectCreate(0, name, OBJ_TREND, 0, r[breaks[i].swingBar].time, breaks[i].level, r[breaks[i].bar].time, breaks[i].level);
      ObjectSetInteger(0, name, OBJPROP_COLOR, c);
      ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_DASH);
      ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
      string text = name + "_t";
      ObjectCreate(0, text, OBJ_TEXT, 0, r[breaks[i].bar].time, breaks[i].level);
      ObjectSetString(0, text, OBJPROP_TEXT, breaks[i].isMSB ? "MSB" : "BOS");
      ObjectSetInteger(0, text, OBJPROP_COLOR, c);
      ObjectSetInteger(0, text, OBJPROP_FONTSIZE, 8);
      ObjectSetInteger(0, text, OBJPROP_ANCHOR, breaks[i].dir > 0 ? ANCHOR_LOWER : ANCHOR_UPPER);
     }
   ChartRedraw(0);
  }

string TradeState(CMarket *m)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(PositionGetTicket(i) > 0 && PositionGetString(POSITION_SYMBOL) == m.symbol && PositionGetInteger(POSITION_MAGIC) == InpMagic)
         return StringFormat("%s %.2f lots, P/L %.2f", PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY ? "long" : "short",
                             PositionGetDouble(POSITION_VOLUME), PositionGetDouble(POSITION_PROFIT));
   for(int i = OrdersTotal() - 1; i >= 0; i--)
      if(OrderGetTicket(i) > 0 && OrderGetString(ORDER_SYMBOL) == m.symbol && OrderGetInteger(ORDER_MAGIC) == InpMagic)
         return "limit order waiting";
   if(m.sigDir != 0)
      return "entry waiting for a normal spread";
   return "";
  }

void UpdateDashboard()
  {
   if(g_tester && !MQLInfoInteger(MQL_VISUAL_MODE))
      return;
   datetime now = TimeCurrent();
   bool algo = TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) && MQLInfoInteger(MQL_TRADE_ALLOWED);
   string s = StringFormat("FxBot %s  |  %s structure  |  risk %.2f%%/trade  |  trades %d/%d%s\n",
                           FXBOT_VERSION, StringSubstr(EnumToString(InpTimeframe), 7), InpRiskPercent,
                           CountOurTrades(), InpMaxTrades, algo ? "" : "  |  ALGO TRADING IS OFF");
   string age = g_biasNewest > 0 ? StringFormat("newest week starts %s", TimeToString(g_biasNewest, TIME_DATE)) : "no rows";
   s += "Bias: " + (InpUseBiasFile ? g_biasStatus + ", " + age : "manual only") + "\n";
   int missing = 0, shown = 0;
   for(int i = 0; i < ArraySize(g_markets); i++)
     {
      CMarket *m = g_markets[i];
      if(!m.ok)
        {
         missing++;
         continue;
        }
      int dir = 0;
      string grade = "-";
      double carry = 0;
      bool stale = true;
      bool have = GetBias(m, now, dir, grade, carry, stale);
      string state = TradeState(m);
      if((!have || dir == 0) && state == "")
         continue;
      s += StringFormat("%s  %s %s%s  carry %+.2f  |  trend %s  |  last %s%s\n", m.pair,
                        dir > 0 ? "BUY " : (dir < 0 ? "SELL" : "----"), grade, stale ? " (stale)" : "", carry,
                        m.trend > 0 ? "up" : (m.trend < 0 ? "down" : "?"), m.lastBreak,
                        state == "" ? "" : "  |  " + state);
      shown++;
     }
   if(shown == 0)
      s += "No pair has a bias right now.\n";
   if(missing > 0)
      s += StringFormat("%d symbols not found at this broker - check InpSymbolSuffix\n", missing);
   Comment(s);
  }
//+------------------------------------------------------------------+
