import pandas as pd
import numpy as np
import talib
import ccxt


api_key = 'your_api_key'
secret_key = 'your_secret_key'


exchange = ccxt.binance({
    'apiKey': api_key,
    'secret': secret_key,
    'enableRateLimit': True
})



def trading_strategy(df):
    # Calculate technical indicators using TA-Lib
    df['SMA20'] = talib.SMA(df['close'], timeperiod=20)
    df['SMA50'] = talib.SMA(df['close'], timeperiod=50)
    df['RSI'] = talib.RSI(df['close'], timeperiod=14)

    # Entry condition
    if df['SMA20'].iloc[-1] > df['SMA50'].iloc[-1] and df['RSI'].iloc[-1] < 30:
        return 'buy'

    # Exit condition
    elif df['SMA20'].iloc[-1] < df['SMA50'].iloc[-1]:
        return 'sell'

    # Hold if no signal
    else:
        return 'hold'
    


def get_market_data(symbol, timeframe):
    ohlc = exchange.fetch_ohlcv(symbol=symbol, timeframe=timeframe)
    df = pd.DataFrame(ohlc, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    return df


def execute_trade(symbol, side, quantity):
    exchange.create_order(symbol=symbol, type='market', side=side, amount=quantity)


def main():
    symbol = 'BTC/USDT'
    timeframe = '1h'
    quantity = 0.001

    while True:
        # Get market data
        df = get_market_data(symbol, timeframe)

        # Execute trades based on trading strategy
        signal = trading_strategy(df)
        if signal == 'buy':
            execute_trade(symbol, 'buy', quantity)
        elif signal == 'sell':
            execute_trade(symbol, 'sell', quantity)

        # Wait for next candle
        time.sleep(60 * 60)  # wait for 1 hour before checking again

