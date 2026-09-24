//+------------------------------------------------------------------+
//|                                                   ExportBars.mq5 |
//|  Research helper for fxbot. Run it in the Strategy Tester (open  |
//|  prices, any chart) and it writes every symbol's bars from your  |
//|  broker's history to Common\Files\<InpFolder>\<SYMBOL>_<TF>.bin: |
//|  int64 time, int32 open/high/low/close in points, int32 spread.  |
//|  <InpFolder>\meta.csv lists each symbol's point size; symbols the |
//|  broker doesn't offer are skipped.                               |
//+------------------------------------------------------------------+
#property copyright   "Chebon Kibet"
#property link        "https://forexchart-kibet.web.app"
#property version     "1.00"
#property description "Research helper: exports broker bars of many symbols to Common\\Files\\bars (run in the Strategy Tester)."

input string          InpSymbols   = "EURUSD,GBPUSD,AUDUSD,NZDUSD,USDCAD,USDCHF,USDJPY,EURGBP,EURAUD,EURNZD,EURCAD,EURCHF,EURJPY,GBPAUD,GBPNZD,GBPCAD,GBPCHF,GBPJPY,AUDNZD,AUDCAD,AUDCHF,AUDJPY,NZDCAD,NZDCHF,NZDJPY,CADCHF,CADJPY,CHFJPY"; // Symbols
input ENUM_TIMEFRAMES InpTimeframe = PERIOD_M15;         // Bars to export
input datetime        InpFrom      = D'2010.01.01 00:00'; // Export bars from
input string          InpFolder    = "bars";              // Folder inside Common\Files

string   g_symbols[];
int      g_files[];
datetime g_done[];   // open time of the last bar written, per symbol
double   g_point[];
long     g_rows[];
datetime g_lastDay = 0;

int OnInit()
  {
   string items[];
   int n = StringSplit(InpSymbols, ',', items);
   ArrayResize(g_symbols, n);
   ArrayResize(g_files, n);
   ArrayResize(g_done, n);
   ArrayResize(g_point, n);
   ArrayResize(g_rows, n);
   ArrayInitialize(g_files, INVALID_HANDLE); // so cleanup is safe even if we fail below
   string tf = StringSubstr(EnumToString(InpTimeframe), 7);
   int meta = FileOpen(InpFolder + "\\meta.csv", FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ',');
   if(meta == INVALID_HANDLE)
      return INIT_FAILED;
   FileWrite(meta, "symbol", "timeframe", "digits", "point");
   for(int i = 0; i < n; i++)
     {
      g_symbols[i] = items[i];
      StringTrimLeft(g_symbols[i]);
      StringTrimRight(g_symbols[i]);
      g_files[i] = INVALID_HANDLE;
      g_done[i] = 0;
      g_rows[i] = 0;
      if(!SymbolSelect(g_symbols[i], true))
        {
         PrintFormat("%s not offered - skipped", g_symbols[i]);
         continue;
        }
      g_point[i] = SymbolInfoDouble(g_symbols[i], SYMBOL_POINT);
      g_files[i] = FileOpen(InpFolder + "\\" + g_symbols[i] + "_" + tf + ".bin", FILE_WRITE | FILE_BIN | FILE_COMMON);
      if(g_files[i] == INVALID_HANDLE)
         return INIT_FAILED;
      g_done[i] = 0;
      g_rows[i] = 0;
      FileWrite(meta, g_symbols[i], tf, (int)SymbolInfoInteger(g_symbols[i], SYMBOL_DIGITS), DoubleToString(g_point[i], 8));
     }
   FileClose(meta);
   return INIT_SUCCEEDED;
  }

//--- once per day, write every finished bar since the last export
void OnTick()
  {
   datetime day = TimeCurrent() - TimeCurrent() % 86400;
   if(day == g_lastDay)
      return;
   g_lastDay = day;
   for(int i = 0; i < ArraySize(g_symbols); i++)
      if(g_files[i] != INVALID_HANDLE)
         Flush(i, day - 1);
  }

void Flush(const int i, const datetime until)
  {
   MqlRates r[];
   datetime from = g_done[i] == 0 ? InpFrom : g_done[i] + 1;
   if(from > until)
      return;
   int n = CopyRates(g_symbols[i], InpTimeframe, from, until, r);
   for(int k = 0; k < n; k++)
     {
      if(r[k].time <= g_done[i])
         continue;
      FileWriteLong(g_files[i], (long)r[k].time);
      FileWriteInteger(g_files[i], (int)MathRound(r[k].open / g_point[i]));
      FileWriteInteger(g_files[i], (int)MathRound(r[k].high / g_point[i]));
      FileWriteInteger(g_files[i], (int)MathRound(r[k].low / g_point[i]));
      FileWriteInteger(g_files[i], (int)MathRound(r[k].close / g_point[i]));
      FileWriteInteger(g_files[i], r[k].spread);
      g_done[i] = r[k].time;
      g_rows[i]++;
     }
  }

void OnDeinit(const int reason)
  {
   for(int i = 0; i < ArraySize(g_symbols); i++)
     {
      if(g_files[i] == INVALID_HANDLE)
         continue;
      Flush(i, TimeCurrent() - TimeCurrent() % 86400 - 1);
      FileClose(g_files[i]);
      PrintFormat("%s: %I64d bars exported", g_symbols[i], g_rows[i]);
     }
  }
