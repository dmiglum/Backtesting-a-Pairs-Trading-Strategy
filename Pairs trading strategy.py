
 
import matplotlib.pyplot as plt
import numpy as np
import os, os.path
import pandas as pd
from statsmodels.tsa.stattools import adfuller
from statsmodels.regression.rolling import RollingOLS
from statsmodels.regression.linear_model import OLS


def create_pairs_dataframe(symbols):
    """Creates a pandas DataFrame containing the closing price
    of a pair of symbols based on CSV files containing a datetime
    stamp and OHLCV data."""

    # Open the individual CSV files and read into pandas DataFrames
    sym1 = pd.io.parsers.read_csv("1_min_SPY_data.csv",
                                  header=0, index_col=0, 
                                  names=['datetime','open','high','low','close','volume','na'])
    sym2 = pd.io.parsers.read_csv("1_min_IWM_data.csv",
                                  header=0, index_col=0, 
                                  names=['datetime','open','high','low','close','volume','na'])

    # Create a pandas DataFrame with the close prices of each symbol
    # correctly aligned and dropping missing entries
    pairs = pd.DataFrame(index=sym1.index)
    pairs['%s_close' % symbols[0].lower()] = sym1['close']
    pairs['%s_close' % symbols[1].lower()] = sym2['close']
    pairs = pairs.dropna()
    return pairs

symbols = ('SPY', 'IWM')
pairs = create_pairs_dataframe(symbols)


def calculate_spread_zscore(pairs, symbols, lookback=100):
    """Creates a hedge ratio between the two symbols by calculating
    a rolling linear regression with a defined lookback period. This
    is then used to create a z-score of the 'spread' between the two
    symbols based on a linear combination of the two."""
    
    # Use the pandas Ordinary Least Squares method to fit a rolling
    # linear regression between the two closing price time series
    model = RollingOLS(endog=pairs['%s_close' % symbols[0].lower()], 
                   exog=pairs['%s_close' % symbols[1].lower()],
                   window=lookback) #I added the intercept = 0, in original code it is not there

    # Construct the hedge ratio and eliminate the first 
    # lookback-length empty/NaN period
    pairs['hedge_ratio'] = model.fit().params
    pairs = pairs.dropna()

    # Create the spread and then a z-score of the spread
    pairs['spread'] = pairs['spy_close'] - pairs['hedge_ratio']*pairs['iwm_close']
    pairs['zscore'] = (pairs['spread'] - np.mean(pairs['spread']))/np.std(pairs['spread'])
    return pairs

regression_df = calculate_spread_zscore(pairs, symbols, lookback=100)

#adf_test of the residual of the linear regression, counting instances and plotting the spread
test_regression = regression_df.iloc[100:]['spread'] #removing first 100 rows since they didn't have enough data to build an accurate regression
adf_test = adfuller(test_regression) #the more negative our result is, the more likely we have
                                                        #a stationary dataset - in this case -13 is way more negative than
                                                        #1% threshold of -3.43, indicating a very stationary dataset
#Counting number of occurrences when spread moves greater than 1 or less than -1
(test_regression>1.0).sum()
(test_regression< -1.0).sum()
#plotting results 
test_regression.plot()


######################  Outputting tp csv ###############
regression_df.to_csv('regression_df.csv')


###############################

def create_long_short_market_signals(pairs, symbols, 
                                     z_entry_threshold=2.0, 
                                     z_exit_threshold=1.0):
    """Create the entry/exit signals based on the exceeding of 
    z_enter_threshold for entering a position and falling below
    z_exit_threshold for exiting a position."""

    # Calculate when to be long, short and when to exit
    pairs['longs'] = (pairs['zscore'] <= -z_entry_threshold)*1.0
    pairs['shorts'] = (pairs['zscore'] >= z_entry_threshold)*1.0
    pairs['exits'] = (np.abs(pairs['zscore']) <= z_exit_threshold)*1.0

    # These signals are needed because we need to propagate a
    # position forward, i.e. we need to stay long if the zscore
    # threshold is less than z_entry_threshold by still greater
    # than z_exit_threshold, and vice versa for shorts.
    pairs['long_market'] = 0.0
    pairs['short_market'] = 0.0

    # These variables track whether to be long or short while
    # iterating through the bars
    long_market = 0
    short_market = 0

    # Calculates when to actually be "in" the market, i.e. to have a
    # long or short position, as well as when not to be.
    # Since this is using iterrows to loop over a dataframe, it will
    # be significantly less efficient than a vectorised operation,
    # i.e. slow!
    for i, b in enumerate(pairs.iterrows()):
        # Calculate longs
        if b[1]['longs'] == 1.0:
            long_market = 1            
        # Calculate shorts
        if b[1]['shorts'] == 1.0:
            short_market = 1
        # Calculate exists
        if b[1]['exits'] == 1.0:
            long_market = 0
            short_market = 0
        # This directly assigns a 1 or 0 to the long_market/short_market
        # columns, such that the strategy knows when to actually stay in!
        pairs.iloc[i]['long_market'] = long_market
        pairs.iloc[i]['short_market'] = short_market
    return pairs

market_signal = create_long_short_market_signals(regression_df, symbols, 
                    z_entry_threshold=2.0, z_exit_threshold=1.0)

(market_signal['zscore']>2.0).sum()
(market_signal['zscore']<-2.0).sum()

#subtracting first 100 rows on which initial regression didn't have enough observations
market_signal = market_signal.iloc[100:]


def create_portfolio_returns(pairs, symbols):
    """Creates a portfolio pandas DataFrame which keeps track of
    the account equity and ultimately generates an equity curve.
    This can be used to generate drawdown and risk/reward ratios."""
    
    # Convenience variables for symbols
    sym1 = symbols[0].lower()
    sym2 = symbols[1].lower()

    # Construct the portfolio object with positions information
    # Note that minuses to keep track of shorts!
    portfolio = pd.DataFrame(index=pairs.index)
    portfolio['positions'] = pairs['long_market'] - pairs['short_market']
    portfolio[sym1] = -1.0 * pairs['%s_close' % sym1] * portfolio['positions']
    portfolio[sym2] = pairs['%s_close' % sym2] * portfolio['positions']
    portfolio['total'] = portfolio[sym1] + portfolio[sym2]

    # Construct a percentage returns stream and eliminate all 
    # of the NaN and -inf/+inf cells
    portfolio['returns'] = portfolio['total'].pct_change()
    portfolio['returns'].fillna(0.0, inplace=True)
    portfolio['returns'].replace([np.inf, -np.inf], 0.0, inplace=True)
    portfolio['returns'].replace(-1.0, 0.0, inplace=True)

    # Calculate the full equity curve
    portfolio['returns'] = (portfolio['returns'] + 1.0).cumprod()
    return portfolio

portfolio = create_portfolio_returns(market_signal, symbols)


#plotting results
fig = plt.figure()
fig.patch.set_facecolor('white')

ax1 = fig.add_subplot(211,  ylabel='%s growth (%%)' % symbols[0])
(market_signal['%s_close' % symbols[0].lower()].pct_change()+1.0).cumprod().plot(ax=ax1, color='r', lw=2.)

ax2 = fig.add_subplot(212, ylabel='Portfolio value growth (%%)')
portfolio['returns'].plot(ax=ax2, lw=2.)

fig.show()
