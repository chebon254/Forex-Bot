//+------------------------------------------------------------------+
//|                                              MarketStructure.mq5 |
//|  Your strategy as a chart tool - it draws, it never trades:      |
//|   - swing labels: H/L, then HH, HL (green) and LH, LL (red)      |
//|   - structure breaks: MSB (against the trend), BOS (with it)     |
//|   - panel: trend on this timeframe and a higher one, plus the    |
//|     weekly COT + interest-rate bias written by `fxbot export`    |
//|   - optional alert when a break lines up with the bias           |
//|  Same swing/break rules as fxbot/structure.py and FxBot.mq5.     |
//|  Nothing repaints: a swing appears once N candles have closed    |
//|  after it, a break only on a candle's close.                     |
//|  From code (iCustom): each "input group" heading takes a slot -  |
//|  pass "" for it. Buffer 0 = trend (+1 up, -1 down).              |
//+------------------------------------------------------------------+
#property copyright   "Chebon Kibet"
#property link        "https://forexchart-kibet.web.app"
#property version     "1.00"
#property description "Market structure (HH/HL/LH/LL, MSB/BOS) with the fxbot COT + interest-rate bias. Draws only; never trades."
#property indicator_chart_window
#property indicator_buffers 1
#property indicator_plots   1
#property indicator_type1   DRAW_NONE
#property indicator_label1  "Trend (+1 up, -1 down)"

#define MS_PREFIX "MS_"

input group "Structure"
input int             InpSwingStrength = 3;         // Candles each side of a swing point
input int             InpLookbackBars  = 500;       // Candles to analyse
input int             InpMaxLabels     = 60;        // Most recent swing labels to draw
input int             InpMaxBreaks     = 20;        // Most recent breaks to draw
input bool            InpShowBOS       = true;      // Draw continuation breaks (BOS) too
input ENUM_TIMEFRAMES InpHigherTF      = PERIOD_D1; // Higher timeframe shown in the panel

input group "Fundamental bias (from fxbot export)"
input bool   InpShowBias = true;             // Show the COT + interest-rate bias
input string InpBiasFile = "fxbot_bias.csv"; // Bias file in MT5 Common\Files

input group "Alerts"
input bool InpAlert             = false; // Pop-up alert on a new MSB
input bool InpAlertBOS          = false; // ...and on a BOS
input bool InpAlertOnlyWithBias = true;  // Only when the break matches the bias
input bool InpPush              = false; // Also send it to the MetaTrader phone app

input group "Look"
input color            InpBullColor  = clrSeaGreen;       // Bullish: HH, HL, breaks up
input color            InpBearColor  = clrCrimson;        // Bearish: LH, LL, breaks down
input color            InpPlainColor = clrGray;           // First swing (H, L) and panel text
input int              InpFontSize   = 8;                 // Label size
input ENUM_BASE_CORNER InpCorner     = CORNER_LEFT_LOWER; // Panel corner

struct Swing
  {
   int               bar;
   double            price;
   bool              isHigh;
   string            label;
  };

struct Break
  {
   int               bar;
   int               dir;   // +1 broke a high, -1 broke a low
   bool              isMSB;
   double            level;
   int               swingBar;
  };

double   g_trendBuffer[];
datetime g_lastBarTime  = 0;
datetime g_lastAlertBar = 0;
int      g_chartTrend   = 0;
string   g_chartLast    = "";
// weekly bias for this pair
bool     g_biasFound = false;
int      g_biasDir = 0, g_baseSide = 0, g_quoteSide = 0;
string   g_biasGrade = "-", g_biasReport = "?", g_biasStatus = "";
double   g_biasCarry = 0;
datetime g_biasFrom = 0;

//+------------------------------------------------------------------+
int OnInit()
  {
   if(InpSwingStrength < 1 || InpLookbackBars < 50)
     {
      Print("Swing strength must be 1+ and lookback 50+");
      return INIT_PARAMETERS_INCORRECT;
     }
   SetIndexBuffer(0, g_trendBuffer, INDICATOR_CALCULATIONS);
   PlotIndexSetDouble(0, PLOT_EMPTY_VALUE, EMPTY_VALUE);
   IndicatorSetString(INDICATOR_SHORTNAME, "MarketStructure");
   EventSetTimer(30); // keeps the panel (higher timeframe, bias) fresh between candles
   return INIT_SUCCEEDED;
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   ObjectsDeleteAll(0, MS_PREFIX);
   ChartRedraw(0);
  }

void OnTimer()
  {
   Panel();
  }

//+------------------------------------------------------------------+
int OnCalculate(const int rates_total, const int prev_calculated, const datetime &time[], const double &open[],
                const double &high[], const double &low[], const double &close[], const long &tick_volume[],
                const long &volume[], const int &spread[])
  {
   if(rates_total < 2 * InpSwingStrength + 20)
      return 0;
   if(prev_calculated > 0 && time[rates_total - 1] == g_lastBarTime)
      return rates_total; // nothing new until the next candle opens
   g_lastBarTime = time[rates_total - 1];

   int to = rates_total - 2; // last closed candle
   int from = MathMax(0, to - InpLookbackBars + 1);
   Swing swings[];
   Break breaks[];
   g_chartTrend = Analyze(high, low, close, from, to, swings, breaks);

   // trend per candle for other tools (Data Window, iCustom)
   ArrayInitialize(g_trendBuffer, EMPTY_VALUE);
   g_trendBuffer[to] = g_chartTrend;
   g_trendBuffer[rates_total - 1] = g_chartTrend;

   int nb = ArraySize(breaks);
   g_chartLast = nb > 0 ? StringFormat("last %s %s %s at %s", breaks[nb - 1].isMSB ? "MSB" : "BOS",
                                       breaks[nb - 1].dir > 0 ? "up" : "down",
                                       TimeToString(time[breaks[nb - 1].bar], TIME_DATE | TIME_MINUTES),
                                       DoubleToString(breaks[nb - 1].level, _Digits)) : "no break yet";
   Draw(time, swings, breaks);
   Panel();
   CheckAlert(breaks, time, to, prev_calculated == 0);
   return rates_total;
  }

//+------------------------------------------------------------------+
//| The structure rules (same as the bots)                           |
//+------------------------------------------------------------------+
int Analyze(const double &high[], const double &low[], const double &close[], const int from, const int to,
            Swing &swings[], Break &breaks[])
  {
   ArrayResize(swings, 0);
   ArrayResize(breaks, 0);
   int s = InpSwingStrength, trend = 0;
   double hiPrice = 0, loPrice = 0, lastHigh = 0, lastLow = 0;
   int hiBar = -1, loBar = -1;
   bool hiBroken = true, loBroken = true, haveHigh = false, haveLow = false;
   for(int t = from; t <= to; t++)
     {
      int i = t - s;
      if(i >= from + s)
        {
         if(IsSwingHigh(high, i, s))
           {
            AddSwing(swings, i, high[i], true, !haveHigh ? "H" : (high[i] > lastHigh ? "HH" : "LH"));
            lastHigh = high[i];
            haveHigh = true;
            hiPrice = high[i];
            hiBar = i;
            hiBroken = false;
           }
         if(IsSwingLow(low, i, s))
           {
            AddSwing(swings, i, low[i], false, !haveLow ? "L" : (low[i] < lastLow ? "LL" : "HL"));
            lastLow = low[i];
            haveLow = true;
            loPrice = low[i];
            loBar = i;
            loBroken = false;
           }
        }
      if(hiBar >= 0 && !hiBroken && close[t] > hiPrice)
        {
         hiBroken = true;
         AddBreak(breaks, t, 1, trend != 1, hiPrice, hiBar);
         trend = 1;
        }
      if(loBar >= 0 && !loBroken && close[t] < loPrice)
        {
         loBroken = true;
         AddBreak(breaks, t, -1, trend != -1, loPrice, loBar);
         trend = -1;
        }
     }
   return trend;
  }

bool IsSwingHigh(const double &high[], const int i, const int s)
  {
   for(int k = i - s; k < i; k++)
      if(high[k] >= high[i])
         return false;
   for(int k = i + 1; k <= i + s; k++)
      if(high[k] > high[i])
         return false;
   return true;
  }

bool IsSwingLow(const double &low[], const int i, const int s)
  {
   for(int k = i - s; k < i; k++)
      if(low[k] <= low[i])
         return false;
   for(int k = i + 1; k <= i + s; k++)
      if(low[k] < low[i])
         return false;
   return true;
  }

void AddSwing(Swing &arr[], const int bar, const double price, const bool isHigh, const string label)
  {
   int k = ArraySize(arr);
   ArrayResize(arr, k + 1, 64);
   arr[k].bar = bar;
   arr[k].price = price;
   arr[k].isHigh = isHigh;
   arr[k].label = label;
  }

void AddBreak(Break &arr[], const int bar, const int dir, const bool isMSB, const double level, const int swingBar)
  {
   int k = ArraySize(arr);
   ArrayResize(arr, k + 1, 32);
   arr[k].bar = bar;
   arr[k].dir = dir;
   arr[k].isMSB = isMSB;
   arr[k].level = level;
   arr[k].swingBar = swingBar;
  }

//+------------------------------------------------------------------+
//| Drawing                                                          |
//+------------------------------------------------------------------+
void Draw(const datetime &time[], const Swing &swings[], const Break &breaks[])
  {
   ObjectsDeleteAll(0, MS_PREFIX + "s");
   ObjectsDeleteAll(0, MS_PREFIX + "b");
   int ns = ArraySize(swings);
   for(int k = MathMax(0, ns - InpMaxLabels); k < ns; k++)
     {
      string label = swings[k].label;
      color c = (label == "HH" || label == "HL") ? InpBullColor : ((label == "LH" || label == "LL") ? InpBearColor : InpPlainColor);
      string name = MS_PREFIX + "s" + IntegerToString(k);
      ObjectCreate(0, name, OBJ_TEXT, 0, time[swings[k].bar], swings[k].price);
      ObjectSetString(0, name, OBJPROP_TEXT, label);
      ObjectSetInteger(0, name, OBJPROP_COLOR, c);
      ObjectSetInteger(0, name, OBJPROP_FONTSIZE, InpFontSize);
      ObjectSetInteger(0, name, OBJPROP_ANCHOR, swings[k].isHigh ? ANCHOR_LOWER : ANCHOR_UPPER);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
     }
   int drawn = 0;
   for(int k = ArraySize(breaks) - 1; k >= 0 && drawn < InpMaxBreaks; k--)
     {
      if(!breaks[k].isMSB && !InpShowBOS)
         continue;
      drawn++;
      color c = breaks[k].dir > 0 ? InpBullColor : InpBearColor;
      string name = MS_PREFIX + "b" + IntegerToString(k);
      ObjectCreate(0, name, OBJ_TREND, 0, time[breaks[k].swingBar], breaks[k].level, time[breaks[k].bar], breaks[k].level);
      ObjectSetInteger(0, name, OBJPROP_COLOR, c);
      ObjectSetInteger(0, name, OBJPROP_STYLE, STYLE_DASH);
      ObjectSetInteger(0, name, OBJPROP_RAY_RIGHT, false);
      ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
      string text = name + "t";
      ObjectCreate(0, text, OBJ_TEXT, 0, time[breaks[k].bar], breaks[k].level);
      ObjectSetString(0, text, OBJPROP_TEXT, breaks[k].isMSB ? "MSB" : "BOS");
      ObjectSetInteger(0, text, OBJPROP_COLOR, c);
      ObjectSetInteger(0, text, OBJPROP_FONTSIZE, InpFontSize);
      ObjectSetInteger(0, text, OBJPROP_ANCHOR, breaks[k].dir > 0 ? ANCHOR_LOWER : ANCHOR_UPPER);
      ObjectSetInteger(0, text, OBJPROP_SELECTABLE, false);
      ObjectSetInteger(0, text, OBJPROP_HIDDEN, true);
     }
   ChartRedraw(0);
  }

//+------------------------------------------------------------------+
//| Panel: trends and the weekly bias                                |
//+------------------------------------------------------------------+
void Panel()
  {
   string lines[];
   color colors[];
   string tf = StringSubstr(EnumToString(_Period), 7);
   AddLine(lines, colors, "Market structure (fxbot) - " + _Symbol, InpPlainColor);
   AddLine(lines, colors, StringFormat("%s: %s  |  %s", tf, TrendWord(g_chartTrend), g_chartLast), TrendColor(g_chartTrend));
   if(PeriodSeconds(InpHigherTF) > PeriodSeconds(_Period))
     {
      int htfTrend = 0;
      string htfLast = HigherTimeframe(htfTrend);
      AddLine(lines, colors, StringFormat("%s: %s  |  %s", StringSubstr(EnumToString(InpHigherTF), 7), TrendWord(htfTrend), htfLast),
              TrendColor(htfTrend));
     }
   if(InpShowBias)
     {
      ReadBias();
      if(g_biasFound)
        {
         string pair = Pair();
         bool stale = TimeCurrent() - g_biasFrom > 10 * 86400;
         AddLine(lines, colors, StringFormat("Bias (COT + rates): %s  grade %s  carry %+.2f%%%s", DirWord(g_biasDir), g_biasGrade,
                                             g_biasCarry, stale ? "  - STALE, run fxbot export" : ""), DirColor(g_biasDir));
         AddLine(lines, colors, StringFormat("%s %s, %s %s  |  COT report %s", StringSubstr(pair, 0, 3), SideWord(g_baseSide),
                                             StringSubstr(pair, 3, 3), SideWord(g_quoteSide), g_biasReport), InpPlainColor);
         if(g_biasDir != 0)
            AddLine(lines, colors, g_chartTrend == g_biasDir ? "Structure agrees with the bias" : "Waiting for a break in the bias direction",
                    g_chartTrend == g_biasDir ? DirColor(g_biasDir) : InpPlainColor);
        }
      else
         AddLine(lines, colors, "Bias: " + g_biasStatus, InpPlainColor);
     }

   int n = ArraySize(lines), height = InpFontSize + 9;
   bool bottom = (InpCorner == CORNER_LEFT_LOWER || InpCorner == CORNER_RIGHT_LOWER);
   bool right = (InpCorner == CORNER_RIGHT_UPPER || InpCorner == CORNER_RIGHT_LOWER);
   ENUM_ANCHOR_POINT anchor = bottom ? (right ? ANCHOR_RIGHT_LOWER : ANCHOR_LEFT_LOWER) : (right ? ANCHOR_RIGHT_UPPER : ANCHOR_LEFT_UPPER);
   for(int row = 0; row < n; row++)
     {
      string name = MS_PREFIX + "p" + IntegerToString(row);
      if(ObjectFind(0, name) < 0)
        {
         ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
         ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
         ObjectSetInteger(0, name, OBJPROP_HIDDEN, true);
         ObjectSetString(0, name, OBJPROP_FONT, "Arial");
        }
      ObjectSetInteger(0, name, OBJPROP_CORNER, InpCorner);
      ObjectSetInteger(0, name, OBJPROP_ANCHOR, anchor);
      ObjectSetInteger(0, name, OBJPROP_XDISTANCE, 12);
      ObjectSetInteger(0, name, OBJPROP_YDISTANCE, 24 + (bottom ? n - 1 - row : row) * height);
      ObjectSetInteger(0, name, OBJPROP_FONTSIZE, InpFontSize + 1);
      ObjectSetString(0, name, OBJPROP_TEXT, lines[row]);
      ObjectSetInteger(0, name, OBJPROP_COLOR, colors[row]);
     }
   for(int row = n; row < 10; row++)
      ObjectDelete(0, MS_PREFIX + "p" + IntegerToString(row));
   ChartRedraw(0);
  }

string HigherTimeframe(int &trend)
  {
   trend = 0;
   MqlRates r[];
   int n = CopyRates(_Symbol, InpHigherTF, 1, InpLookbackBars, r);
   if(n < 2 * InpSwingStrength + 20)
      return "loading history...";
   double h[], l[], c[];
   ArrayResize(h, n);
   ArrayResize(l, n);
   ArrayResize(c, n);
   for(int k = 0; k < n; k++)
     {
      h[k] = r[k].high;
      l[k] = r[k].low;
      c[k] = r[k].close;
     }
   Swing swings[];
   Break breaks[];
   trend = Analyze(h, l, c, 0, n - 1, swings, breaks);
   int nb = ArraySize(breaks);
   if(nb == 0)
      return "no break yet";
   return StringFormat("last %s %s %s", breaks[nb - 1].isMSB ? "MSB" : "BOS", breaks[nb - 1].dir > 0 ? "up" : "down",
                       TimeToString(r[breaks[nb - 1].bar].time, TIME_DATE));
  }

//--- the pair's newest bias row that is already in force (re-read each time: the file is tiny)
void ReadBias()
  {
   g_biasFound = false;
   string pair = Pair();
   int h = FileOpen(InpBiasFile, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON | FILE_SHARE_READ | FILE_SHARE_WRITE);
   if(h == INVALID_HANDLE)
     {
      g_biasStatus = "no bias file yet - run fxbot export";
      return;
     }
   datetime now = TimeCurrent(), best = 0;
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
            g_biasReport = StringSubstr(line, p + 11, 10);
         continue;
        }
      string f[];
      if(StringSplit(line, ',', f) < 9 || f[0] != pair)
         continue;
      datetime from = (datetime)StringToInteger(f[8]);
      if(from > now || from < best)
         continue;
      best = from;
      g_biasFound = true;
      g_biasFrom = from;
      g_biasDir = f[1] == "BUY" ? 1 : (f[1] == "SELL" ? -1 : 0);
      g_biasGrade = f[2];
      g_biasCarry = StringToDouble(f[3]);
      g_baseSide = (int)StringToInteger(f[5]);
      g_quoteSide = (int)StringToInteger(f[6]);
     }
   FileClose(h);
   if(!g_biasFound)
      g_biasStatus = "none for " + _Symbol + " (the bias covers the 28 currency pairs)";
  }

//--- alert once per candle, only for breaks confirmed on the candle that just closed
void CheckAlert(const Break &breaks[], const datetime &time[], const int lastClosed, const bool firstRun)
  {
   int nb = ArraySize(breaks);
   if(firstRun || nb == 0 || (!InpAlert && !InpPush))
      return;
   if(breaks[nb - 1].bar != lastClosed || time[lastClosed] == g_lastAlertBar)
      return;
   if(!breaks[nb - 1].isMSB && !InpAlertBOS)
      return;
   bool matches = g_biasFound && g_biasDir == breaks[nb - 1].dir;
   if(InpAlertOnlyWithBias && !matches)
      return;
   g_lastAlertBar = time[lastClosed];
   string msg = StringFormat("%s %s: %s %s at %s%s", _Symbol, StringSubstr(EnumToString(_Period), 7),
                             breaks[nb - 1].isMSB ? "MSB" : "BOS", breaks[nb - 1].dir > 0 ? "up" : "down",
                             DoubleToString(breaks[nb - 1].level, _Digits),
                             matches ? StringFormat(" - matches the bias (%s, grade %s)", DirWord(g_biasDir), g_biasGrade) : "");
   if(InpAlert)
      Alert(msg);
   if(InpPush)
      SendNotification(msg);
  }

//+------------------------------------------------------------------+
//| Small helpers                                                    |
//+------------------------------------------------------------------+
string Pair()
  {
   string s = StringSubstr(_Symbol, 0, 6);
   StringToUpper(s);
   return s;
  }

void AddLine(string &lines[], color &colors[], const string text, const color c)
  {
   int k = ArraySize(lines);
   ArrayResize(lines, k + 1);
   ArrayResize(colors, k + 1);
   lines[k] = text;
   colors[k] = c;
  }

string TrendWord(const int t) { return t > 0 ? "UPTREND" : (t < 0 ? "DOWNTREND" : "no trend yet"); }
color  TrendColor(const int t) { return t > 0 ? InpBullColor : (t < 0 ? InpBearColor : InpPlainColor); }
string DirWord(const int d) { return d > 0 ? "BUY" : (d < 0 ? "SELL" : "NEUTRAL"); }
color  DirColor(const int d) { return d > 0 ? InpBullColor : (d < 0 ? InpBearColor : InpPlainColor); }
string SideWord(const int s) { return s > 0 ? "bullish" : (s < 0 ? "bearish" : "flat"); }
//+------------------------------------------------------------------+
