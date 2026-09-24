//+------------------------------------------------------------------+
//|                                                     IndexBot.mq5 |
//|  Two stock-index rules on daily candles, tested in `fxbot lab`:  |
//|    trend: hold while the close is above the 200-day average      |
//|    dip:   buy when RSI(2) closes below 10 above the 200-day      |
//|           average; sell on a close above the 5-day average       |
//|  Acts once a day just before the US close, using that price as   |
//|  the day's close - as the Python test does with official closes.|
//|  Mirrors index_positions() in fxbot/lab.py - keep them in step.  |
//+------------------------------------------------------------------+
#property copyright   "Chebon Kibet"
#property link        "https://forexchart-kibet.web.app"
#property version     "1.00"
#property description "NASDAQ 100 (US100) on daily candles: 200-day trend filter + RSI-2 dip buying."

#include <Trade\Trade.mqh>

#define INDEXBOT_VERSION "1.00"

enum ENUM_INDEX_RULES
  {
   RUN_BOTH  = 0, // Both rules (each at its own size)
   RUN_TREND = 1, // Trend only (above the 200-day average)
   RUN_DIP   = 2  // Dip only (RSI-2)
  };

input group "What to trade"
input string           InpSymbol = "US100";  // Index symbol at your broker
input ENUM_INDEX_RULES InpRules  = RUN_BOTH; // Rules to run

input group "Rules (daily candles; defaults are the tested textbook settings)"
input int    InpTrendDays   = 200; // Trend: average length (days)
input int    InpRsiDays     = 2;   // Dip: RSI period
input double InpRsiBuyBelow = 10;  // Dip: buy when the RSI closes below this
input int    InpExitDays    = 5;   // Dip: sell on a close above this average (days)

input group "Size and execution"
input double InpTrendExposure   = 0.5;      // Trend position value as a multiple of equity (0.5 = half)
input double InpDipExposure     = 0.5;      // Dip position value as a multiple of equity
input string InpTradeTime       = "22:45";  // Server time to act each day (the US close is 23:00 on FBS)
input double InpMaxSpreadPct    = 0.05;     // Wait while the spread is above this % of price
input long   InpMagic           = 26100100; // Magic number base (+1 trend, +2 dip)

CTrade   g_trade;
bool     g_tester    = false;
datetime g_lastScan  = 0;
datetime g_decidedDay = 0;    // server day (midnight) of the last decision
int      g_tradeMinute = 0;   // InpTradeTime as minutes after midnight
int      g_wantTrend = -1;    // 1 = hold long, 0 = flat, -1 = not decided yet
int      g_wantDip   = -1;
double   g_close = 0, g_trendAvg = 0, g_exitAvg = 0, g_rsi = 0;
string   g_lastWarning = "";

long MagicTrend() { return InpMagic + 1; }
long MagicDip()   { return InpMagic + 2; }

//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpTrendDays < 2 || InpRsiDays < 1 || InpExitDays < 1 || InpTrendExposure < 0 || InpDipExposure < 0 ||
      InpTrendExposure > 3 || InpDipExposure > 3)
     {
      Print("Check the inputs: averages of 2+ days, RSI period 1+, exposures between 0 and 3");
      return INIT_PARAMETERS_INCORRECT;
     }
   if(!SymbolSelect(InpSymbol, true))
     {
      PrintFormat("%s is not offered by this broker/account - set InpSymbol to the name in Market Watch", InpSymbol);
      return INIT_PARAMETERS_INCORRECT;
     }
   string hm[];
   if(StringSplit(InpTradeTime, ':', hm) != 2 || StringToInteger(hm[0]) > 23 || StringToInteger(hm[1]) > 59)
     {
      Print("InpTradeTime must look like 22:45");
      return INIT_PARAMETERS_INCORRECT;
     }
   g_tradeMinute = (int)StringToInteger(hm[0]) * 60 + (int)StringToInteger(hm[1]);
   g_tester = (bool)MQLInfoInteger(MQL_TESTER);
   g_trade.SetDeviationInPoints(50);
   g_lastScan = 0;
   g_decidedDay = 0;
   EventSetTimer(30);
   Scan();
   Dashboard();
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   Comment("");
  }

void OnTick()
  {
   Scan();
  }

void OnTimer()
  {
   Scan();
   Dashboard();
  }

//+------------------------------------------------------------------+
//| Once a minute: decide once a day at the trade time, then act     |
//+------------------------------------------------------------------+
void Scan()
  {
   datetime now = TimeCurrent();
   if(now - g_lastScan < 60)
      return;
   g_lastScan = now;

   MqlDateTime t;
   TimeToStruct(now, t);
   datetime day = now - now % 86400;
   if(day != g_decidedDay && t.hour * 60 + t.min >= g_tradeMinute)
     {
      if(!Decide())
         return; // history still loading - try again next minute
      g_decidedDay = day;
      g_lastWarning = "";
     }
   if(g_decidedDay == 0)
      return;
   Reconcile(MagicTrend(), InpRules != RUN_DIP ? g_wantTrend : 0, InpTrendExposure, "trend");
   Reconcile(MagicDip(), InpRules != RUN_TREND ? g_wantDip : 0, InpDipExposure, "dip");
  }

//--- what each rule should hold; today's candle counts, with the current price as its close
bool Decide()
  {
   int need = MathMax(InpTrendDays, InpExitDays) + 60; // + warm-up for the RSI
   MqlRates r[];
   int n = CopyRates(InpSymbol, PERIOD_D1, 0, need, r);
   if(n < need)
      return false;
   double c[];
   ArrayResize(c, n);
   for(int k = 0; k < n; k++)
      c[k] = r[k].close;
   g_close    = c[n - 1];
   g_trendAvg = Average(c, n, InpTrendDays);
   g_exitAvg  = Average(c, n, InpExitDays);
   g_rsi      = Rsi(c, n, InpRsiDays);

   // Trend: long while above the average, flat below it.
   g_wantTrend = g_close > g_trendAvg ? 1 : 0;
   // Dip: an open dip trade is sold on the bounce; otherwise buy a dip in an uptrend.
   if(HasPosition(MagicDip()))
      g_wantDip = g_close > g_exitAvg ? 0 : 1;
   else
      g_wantDip = (g_close > g_trendAvg && g_rsi < InpRsiBuyBelow) ? 1 : 0;
   return true;
  }

double Average(const double &c[], const int n, const int days)
  {
   double sum = 0;
   for(int k = n - days; k < n; k++)
      sum += c[k];
   return sum / days;
  }

//--- Wilder's RSI (exponential average with alpha = 1/period), as in fxbot/lab.py
double Rsi(const double &c[], const int n, const int period)
  {
   double a = 1.0 / period, up = 0, down = 0;
   for(int k = 1; k < n; k++)
     {
      double d = c[k] - c[k - 1];
      double gain = d > 0 ? d : 0, loss = d < 0 ? -d : 0;
      if(k == 1)
        {
         up = gain;
         down = loss;
        }
      else
        {
         up   = (1 - a) * up + a * gain;
         down = (1 - a) * down + a * loss;
        }
     }
   if(down == 0)
      return 100;
   return 100 - 100 / (1 + up / down);
  }

//+------------------------------------------------------------------+
//| Bring one rule's position in line with its target                |
//+------------------------------------------------------------------+
void Reconcile(const long magic, const int want, const double exposure, const string label)
  {
   if(want < 0)
      return;
   bool have = HasPosition(magic);
   if(have && want == 0)
     {
      // Exits are always completed: retried every minute until done.
      if(SpreadOk())
         ClosePositions(magic, label);
      return;
     }
   if(have || want == 0 || exposure <= 0)
      return;
   if(TimeCurrent() - g_decidedDay >= 86400)
      return; // today's signal has expired; tomorrow's decision replaces it
   if(!SpreadOk())
      return;
   double lots = LotsForExposure(exposure, label);
   if(lots <= 0)
      return;
   g_trade.SetExpertMagicNumber((ulong)magic);
   g_trade.SetTypeFillingBySymbol(InpSymbol);
   bool sent = g_trade.Buy(lots, InpSymbol, 0, 0, 0, "IndexBot " + label);
   uint code = g_trade.ResultRetcode();
   if(sent && (code == TRADE_RETCODE_DONE || code == TRADE_RETCODE_PLACED))
      PrintFormat("%s: bought %.2f lots of %s at %s (close %.2f, 200-day %.2f, RSI %.1f)", label, lots, InpSymbol,
                  DoubleToString(g_trade.ResultPrice(), _Digits), g_close, g_trendAvg, g_rsi);
   else
      Warn(StringFormat("%s entry not possible yet: %u %s - retrying", label, code, g_trade.ResultRetcodeDescription()));
  }

bool SpreadOk()
  {
   double bid = SymbolInfoDouble(InpSymbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(InpSymbol, SYMBOL_ASK);
   if(bid <= 0 || ask <= 0)
      return false;
   return (ask - bid) / bid * 100.0 <= InpMaxSpreadPct;
  }

//--- position value = exposure x equity, e.g. 0.5 x $10,000 = $5,000 of index
double LotsForExposure(const double exposure, const string label)
  {
   double price = SymbolInfoDouble(InpSymbol, SYMBOL_ASK);
   double perPercent = 0;
   if(!OrderCalcProfit(ORDER_TYPE_BUY, InpSymbol, 1.0, price, price * 1.01, perPercent) || perPercent <= 0)
      return 0;
   double valuePerLot = perPercent * 100.0;
   double step = SymbolInfoDouble(InpSymbol, SYMBOL_VOLUME_STEP);
   double vmin = SymbolInfoDouble(InpSymbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(InpSymbol, SYMBOL_VOLUME_MAX);
   if(step <= 0)
      step = vmin;
   double lots = MathFloor(AccountInfoDouble(ACCOUNT_EQUITY) * exposure / valuePerLot / step + 1e-9) * step;
   if(lots < vmin)
     {
      Warn(StringFormat("%s skipped: %.2fx equity is %.2f %s, but the smallest trade (%.2f lots) is worth %.2f",
                        label, exposure, AccountInfoDouble(ACCOUNT_EQUITY) * exposure,
                        AccountInfoString(ACCOUNT_CURRENCY), vmin, valuePerLot * vmin));
      return 0;
     }
   lots = MathMin(lots, vmax);
   double margin = 0;
   if(OrderCalcMargin(ORDER_TYPE_BUY, InpSymbol, lots, price, margin) && margin > AccountInfoDouble(ACCOUNT_MARGIN_FREE))
     {
      Warn(StringFormat("%s skipped: not enough free margin for %.2f lots", label, lots));
      return 0;
     }
   int digits = 0;
   for(double s = step; digits < 8 && MathAbs(s - MathRound(s)) > 1e-8; s *= 10)
      digits++;
   return NormalizeDouble(lots, digits);
  }

//--- say a repeated problem once per candle, not once a minute
void Warn(const string text)
  {
   if(text == g_lastWarning)
      return;
   g_lastWarning = text;
   Print(text);
  }

bool HasPosition(const long magic)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(PositionGetTicket(i) > 0 && PositionGetString(POSITION_SYMBOL) == InpSymbol && PositionGetInteger(POSITION_MAGIC) == magic)
         return true;
   return false;
  }

void ClosePositions(const long magic, const string label)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || PositionGetString(POSITION_SYMBOL) != InpSymbol || PositionGetInteger(POSITION_MAGIC) != magic)
         continue;
      double profit = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
      if(g_trade.PositionClose(ticket))
         PrintFormat("%s: sold (close %.2f, 5-day %.2f, 200-day %.2f), result %.2f", label, g_close, g_exitAvg, g_trendAvg, profit);
      else
         Warn(StringFormat("%s exit not possible yet: %s - retrying", label, g_trade.ResultRetcodeDescription()));
     }
  }

string PositionText(const long magic)
  {
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(PositionGetTicket(i) > 0 && PositionGetString(POSITION_SYMBOL) == InpSymbol && PositionGetInteger(POSITION_MAGIC) == magic)
         return StringFormat("LONG %.2f lots, P/L %.2f (swap %.2f)", PositionGetDouble(POSITION_VOLUME),
                             PositionGetDouble(POSITION_PROFIT), PositionGetDouble(POSITION_SWAP));
   return "flat";
  }

void Dashboard()
  {
   if(g_tester && !MQLInfoInteger(MQL_VISUAL_MODE))
      return;
   bool algo = TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) && MQLInfoInteger(MQL_TRADE_ALLOWED);
   string s = StringFormat("IndexBot %s  |  %s daily  |  %s%s\n", INDEXBOT_VERSION, InpSymbol,
                           InpRules == RUN_BOTH ? "trend + dip" : (InpRules == RUN_TREND ? "trend only" : "dip only"),
                           algo ? "" : "  |  ALGO TRADING IS OFF");
   if(g_decidedDay > 0)
      s += StringFormat("Decided at %s: close %.2f  |  %d-day avg %.2f (%s)  |  %d-day avg %.2f  |  RSI(%d) %.1f\n",
                        InpTradeTime, g_close, InpTrendDays, g_trendAvg, g_close > g_trendAvg ? "above: uptrend" : "below: stay out",
                        InpExitDays, g_exitAvg, InpRsiDays, g_rsi);
   else
      s += StringFormat("Decides each day at %s server time (just before the US close)\n", InpTradeTime);
   if(InpRules != RUN_DIP)
      s += StringFormat("Trend (%.2fx): %s\n", InpTrendExposure, PositionText(MagicTrend()));
   if(InpRules != RUN_TREND)
      s += StringFormat("Dip   (%.2fx): %s%s\n", InpDipExposure, PositionText(MagicDip()),
                        HasPosition(MagicDip()) ? "  - sells on a close above the 5-day average" : "  - buys when RSI < 10 in an uptrend");
   if(g_lastWarning != "")
      s += "Note: " + g_lastWarning + "\n";
   Comment(s);
  }
//+------------------------------------------------------------------+
