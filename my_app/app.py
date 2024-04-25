from flask import Flask, request, jsonify
import requests
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import pandas as pd
import statsmodels.api as sm

load_dotenv()

app = Flask(__name__)

IEX_API_TOKEN = os.getenv("IEX_API_TOKEN")

@app.route('/get-return/<string:ticker>', methods=['GET'])
def get_return(ticker):
    try:
        from_date = request.args.get('from_date', default=None, type=str)
        to_date = request.args.get('to_date', default=None, type=str)
        max_days_window = 365*10  # 10 years    

        # Check date range
        if from_date and to_date:
            try:
                from_date_obj = datetime.strptime(from_date, '%Y-%m-%d')
                to_date_obj = datetime.strptime(to_date, '%Y-%m-%d')
                if to_date_obj - from_date_obj > timedelta(days=max_days_window):
                    print("Date range should not exceed 10 year")
                    return jsonify({"error": "Date range should not exceed 10 year"}), 400
            except ValueError:
                return jsonify({"error": "Invalid date format. Use 'YYYY-MM-DD'"}), 400

        # Default to YTD if no dates are provided
        if not from_date and not to_date:
            today = datetime.now()
            # first day of the current year
            from_date = today.strftime('%Y-01-01')
            # current date
            to_date = today.strftime('%Y-%m-%d')
            
        # Fetch historical prices
        url = f'https://api.iex.cloud/v1/data/core/historical_prices/{ticker}?from={from_date}&to={to_date}&token={IEX_API_TOKEN}'
        print(f"API URL: {url}")  # Print the URL for debugging

        response = requests.get(url)
        if response.status_code != 200:
            return jsonify({"error": "Failed to fetch historical prices"}), response.status_code
        
        print("response", response.json())

        response_data = response.json()
        # Sort the response data by priceDate
        response_data = sorted(response_data, key=lambda x: x['priceDate'])

        # Calculate daily returns
        returns = []
        for i in range(len(response_data) - 1, 0, -1):
            daily_return = (response_data[i]['close'] - response_data[i-1]['close']) / response_data[i-1]['close']
            returns.append(
                {
                    "date": response_data[i]['priceDate'],
                    "return": daily_return,
                    "price": response_data[i]['close'],
                }
            )

        return jsonify(returns)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/get-alpha/<string:ticker>/<string:benchmark>', methods=['GET'])
def get_alpha(ticker, benchmark):
    try: 
        from_date = request.args.get('from_date', default=None, type=str)
        to_date = request.args.get('to_date', default=None, type=str)
        treasury_version = "DGS5" # 5-Year Treasury Market Rate


        # Default to YTD if no dates are provided
        if not from_date and not to_date:
            today = datetime.now()
            from_date = today.strftime('%Y-01-01')
            to_date = today.strftime('%Y-%m-%d')

        # Fetch historical prices for ticker
        url_ticker = f'https://api.iex.cloud/v1/data/core/historical_prices/{ticker}?from={from_date}&to={to_date}&token={IEX_API_TOKEN}'
        response_ticker = requests.get(url_ticker)
        if response_ticker.status_code != 200:
            return jsonify({"error": "Failed to fetch ticker historical prices"}), response_ticker.status_code

        response_ticker_json = response_ticker.json()
        response_ticker_json = sorted(response_ticker_json, key=lambda x: x['priceDate'])

        # Fetch historical prices for benchmark
        url_benchmark = f'https://api.iex.cloud/v1/data/core/historical_prices/{benchmark}?from={from_date}&to={to_date}&token={IEX_API_TOKEN}'
        response_benchmark = requests.get(url_benchmark)
        if response_benchmark.status_code != 200:
            return jsonify({"error": "Failed to fetch benchmark historical prices"}), response_benchmark.status_code

        response_benchmark_json = response_benchmark.json()
        response_benchmark_json = sorted(response_benchmark_json, key=lambda x: x['priceDate'])

        # Fetch historical rates for risk-free rate
        url_treasury = f'https://api.iex.cloud/v1/data/core/treasury/{treasury_version}?from={from_date}&to={to_date}&token={IEX_API_TOKEN}'
        response_treasury = requests.get(url_treasury)
        if response_treasury.status_code != 200:
            return jsonify({"error": "Failed to fetch treasury rates"}), response_treasury.status_code
        
        response_treasury_json = response_treasury.json()

        # pre-process the date field in treasury data, such that if it is an int, we convert it to a string
        for i in range(len(response_treasury_json)):
            if isinstance(response_treasury_json[i]['date'], int):
                response_treasury_json[i]['date'] = datetime.fromtimestamp(response_treasury_json[i]['date'] / 1000).strftime('%Y-%m-%d')


        response_treasury_json = sorted(response_treasury_json, key=lambda x: x['date'])
        print("response_treasury_json", response_treasury_json)


        # Get ticker prices and returns
        ticker_data_dict = {}
        first_ticker_price = response_ticker_json[0]['close']

        for i in range(1, len(response_ticker_json)):
            daily_return = (response_ticker_json[i]['close'] - response_ticker_json[i-1]['close']) / response_ticker_json[i-1]['close']
            data_dict = {
                    "daily_return": daily_return,
                    "annualized_daily_return": (1 + daily_return) ** (252) - 1,  # 252 trading days in a year
                    "price": response_ticker_json[i]['close'],
                    "indexed price": response_ticker_json[i]['close'] / first_ticker_price * 100,
            }
            ticker_data_dict[response_ticker_json[i]['priceDate']] = data_dict
        
            

        # Get benchmark prices and returns
        benchmark_data_dict = {}
        first_benchmark_price = response_benchmark_json[0]['close']
        for i in range(1, len(response_benchmark_json)):
            daily_return = (response_benchmark_json[i]['close'] - response_benchmark_json[i-1]['close']) / response_benchmark_json[i-1]['close']
            data_dict = {
                "daily_return": daily_return,
                "annualized_daily_return": (1 + daily_return) ** (252) - 1,  # 252 trading days in a year
                "price": response_benchmark_json[i]['close'],
                "indexed price": response_benchmark_json[i]['close'] / first_benchmark_price * 100,
            }
            benchmark_data_dict[response_benchmark_json[i]['priceDate']] = data_dict
            

        # Get treasury rates
        treasury_data_dict = {}
        for i in range(1, len(response_treasury_json)):
            # Parse the date string to datetime object
            date_obj = None

            # Convert the date string to datetime object
            if is_valid_date(response_treasury_json[i]['date'], '%Y-%m-%d %H:%M:%S'):
                date_obj = datetime.strptime(response_treasury_json[i]['date'], '%Y-%m-%d %H:%M:%S')
            elif is_valid_date(response_treasury_json[i]['date'], '%Y-%m-%d'):
                date_obj = datetime.strptime(response_treasury_json[i]['date'], '%Y-%m-%d')
            
            # Format the datetime object to yyyy-mm-dd string
            date = date_obj.strftime('%Y-%m-%d')


            data_dict = {
                "rate": float(response_treasury_json[i]['value']) / 100,
                "daily_return": (1 + float(response_treasury_json[i]['value']) / 100) ** (1 / (252)) - 1,  # 252 trading days in a year        
            }
            treasury_data_dict[date] = data_dict
            
        # Get unique dates from all datasets
        unique_dates = set(ticker_data_dict.keys()) | set(benchmark_data_dict.keys()) | set(treasury_data_dict.keys())

        # Join the ticker data, benchmark data, and treasury data, by date
        combined_data = []
        for date in sorted(unique_dates):
            ticker_data = ticker_data_dict.get(date, {"daily_return": 0, "annualized_daily_return": 0, "price": 0, "indexed price": 0})
            benchmark_data = benchmark_data_dict.get(date, {"daily_return": 0, "annualized_daily_return": 0, "price": 0, "indexed price": 0})
            treasury_data = treasury_data_dict.get(date, {"rate": 0, "daily_return": 0})
            combined_data.append(
                {
                    "date": date,
                    "risk_free_rate_annualized": treasury_data["rate"],
                    "risk_free_rate_daily": treasury_data["daily_return"],
                    "ticker_price": ticker_data["price"],
                    "benchmark_price": benchmark_data["price"],
                    "ticker_indexed_price": ticker_data["indexed price"],
                    "benchmark_indexed_price": benchmark_data["indexed price"],
                    "ticker_return_daily": ticker_data["daily_return"],
                    "benchmark_return_daily": benchmark_data["daily_return"],
                    "ticker_return_excess_daily": ticker_data["daily_return"] - treasury_data["daily_return"],
                    "benchmark_return_excess_daily": benchmark_data["daily_return"] - treasury_data["daily_return"],
                }
            )
        
        # drop instances of combined data where either ticker_price or benchmark_price is 0
        combined_data = [data for data in combined_data if data["ticker_price"] != 0 and data["benchmark_price"] != 0 and data["risk_free_rate_daily"] != 0]
        
        # drop outliers, where absolute value of ticker return daily or benchmark return daily exceeds 0.50
        combined_data = [data for data in combined_data if abs(data["ticker_return_daily"]) <= 0.50 and abs(data["benchmark_return_daily"]) <= 0.50]

        # Calculate alpha, beta
        # Create a DataFrame from combined_data
        df = pd.DataFrame(combined_data)

        # Drop rows where either ticker_return_excess or benchmark_return_excess is 0
        # df = df[(df['ticker_return_excess'] != 0) & (df['benchmark_return_excess'] != 0)]

        # Define the independent and dependent variables
        X = df['benchmark_return_excess_daily']
        y = df['ticker_return_excess_daily']

        # Add a constant to the independent variable
        X = sm.add_constant(X)

        # Fit the regression model
        model = sm.OLS(y, X).fit()


        # additional metrics
        # Get the R-squared value
        r_squared = model.rsquared

        # Get the standard error for the slope and y-intercept
        beta_se = model.bse['benchmark_return_excess_daily']
        alpha_se = model.bse['const']

        # Get the t-statistic for the slope and y-intercept
        beta_t = model.tvalues['benchmark_return_excess_daily']
        alpha_t = model.tvalues['const']

        # Get the p-value for the slope and y-intercept
        beta_pvalue = model.pvalues['benchmark_return_excess_daily']
        alpha_pvalue = model.pvalues['const']

        # Get the slope (coefficient for benchmark_return_excess) and y-intercept
        beta = model.params['benchmark_return_excess_daily']
        alpha_regression_daily = model.params['const']
        alpha_regression_annualized = (1 + alpha_regression_daily) ** (252) - 1

        ############################################################

        # Get the annualized return for the ticker and benchmark
        first_ticker_price = df['ticker_price'].iloc[0]
        last_ticker_price = df['ticker_price'].iloc[-1]

        first_benchmark_price = df['benchmark_price'].iloc[0]
        last_benchmark_price = df['benchmark_price'].iloc[-1]

        first_date = datetime.strptime(df['date'].iloc[0], '%Y-%m-%d')
        last_date = datetime.strptime(df['date'].iloc[-1], '%Y-%m-%d')

        # Calculate yearfrac between first_date and last_date
        yearfrac = (last_date - first_date).days / 365

        ticker_annualized_return = (last_ticker_price / first_ticker_price) ** (1 / yearfrac) - 1
        benchmark_annualized_return = (last_benchmark_price / first_benchmark_price) ** (1 / yearfrac) - 1

        # Calculate the volatility for the ticker and benchmark
        ticker_annualized_volatility = df['ticker_return_daily'].std() * (252 ** 0.5)
        benchmark_annualized_volatility = df['benchmark_return_daily'].std() * (252 ** 0.5)

        # Calculate the sharpe ratio for the ticker and benchmark
        ticker_sharpe_ratio = (ticker_annualized_return - df['risk_free_rate_annualized'].mean()) / ticker_annualized_volatility
        benchmark_sharpe_ratio = (benchmark_annualized_return - df['risk_free_rate_annualized'].mean()) / benchmark_annualized_volatility

        # add daily alpha to the combined data
        # add a column for alpha_daily

        alpha_geom_aggregator = 1

        for data in combined_data:
            alpha_daily_point = data["ticker_return_excess_daily"] - beta * data["benchmark_return_excess_daily"]
            alpha_geom_aggregator *= (1 + alpha_daily_point)
            data["alpha_daily"] = alpha_daily_point
        
        # Geometric daily alpha
        alpha_geom_daily = alpha_geom_aggregator ** (1 / len(combined_data)) - 1  
        alpha_geom_annualized = (1 + alpha_geom_daily) ** (252) - 1




        return jsonify({"alpha_regression_daily": alpha_regression_daily,
                        "alpha_regression_annualized": alpha_regression_annualized,
                        "alpha_geom_daily": alpha_geom_daily,
                        "alpha_geom_annualized": alpha_geom_annualized,
                        "beta": beta, 
                        "r_squared": r_squared,
                        "alpha_se": alpha_se,
                        "beta_se": beta_se,
                        "alpha_t": alpha_t,
                        "beta_t": beta_t,
                        "alpha_pvalue": alpha_pvalue,
                        "beta_pvalue": beta_pvalue,
                        "ticker_annualized_return": ticker_annualized_return,
                        "benchmark_annualized_return": benchmark_annualized_return,
                        "ticker_annualized_volatility": ticker_annualized_volatility,
                        "benchmark_annualized_volatility": benchmark_annualized_volatility,
                        "ticker_sharpe_ratio": ticker_sharpe_ratio,
                        "benchmark_sharpe_ratio": benchmark_sharpe_ratio,
                        "data": combined_data})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def is_valid_date(date_str, format):
    try:
        datetime.strptime(date_str, format)
        return True
    except ValueError:
        return False