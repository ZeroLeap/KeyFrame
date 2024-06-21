import sys
from flask import Flask, request, jsonify
import ccxt
import logging
from datetime import datetime
import requests
import threading
import time

if sys.version_info < (3, 8):
    import importlib_metadata as importlib_metadata
else:
    import importlib.metadata as importlib_metadata

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)

# Google Form prefilled link
google_form_url = "https://docs.google.com/forms/d/e/**REPLACEWITHFORMID**/formResponse"

def send_google_form_response(order_type, symbol, strike, amount, value, balance):
    form_data = {
        'entry.REPLACEWITHFIELDID: order_type,  # TYPE
        'entry.REPLACEWITHFIELDID': symbol,  # SYMBOL
        'entry.REPLACEWITHFIELDID': strike,  # STRIKE
        'entry.REPLACEWITHFIELDID': amount,  # AMOUNT
        'entry.REPLACEWITHFIELDID': value,  # VALUE
        'entry.REPLACEWITHFIELDID': balance  # BALANCE
    }
    response = requests.post(google_form_url, data=form_data)
    app.logger.info(f"Google Form response status: {response.status_code}, response text: {response.text}")

def delayed_send_google_form_response(order_type, symbol, strike, amount, value, exchange):
    time.sleep(360)  # 6-min delay
    balance = exchange.fetch_balance()
    total_balance_usd = get_total_balance_usd(balance, exchange)
    send_google_form_response(order_type, symbol, strike, amount, value, f"${total_balance_usd:,.2f}")

def get_total_balance_usd(balance, exchange):
    total_usd = 0.0
    free_usd = balance['free'].get('USD', 0)
    total_usd += free_usd

    for currency, amount in balance['free'].items():
        if currency != 'USD' and amount > 0:
            ticker = exchange.fetch_ticker(f"{currency}/USD")
            total_usd += amount * ticker['last']
    return total_usd

def get_available_usd(balance):
    return balance['free'].get('USD', 0)

def execute_order_with_retry(exchange, order_func, symbol, amount, price, retries=3, delay=2):
    for attempt in range(retries):
        try:
            order = order_func(symbol, amount, price)
            app.logger.info(f"Order placed: {order}")
            return order
        except Exception as e:
            app.logger.error(f"Attempt {attempt + 1} failed with error: {e}")
            time.sleep(delay)
    raise Exception(f"All {retries} attempts to execute order failed.")

def round_price(price):
    return round(price, 8)

def cancel_all_orders(exchange):
    try:
        exchange.request('/v1/order/cancel/all', 'POST')
        app.logger.info("Canceled all unfilled orders")
    except Exception as e:
        app.logger.error(f"Error cancelling unfilled orders: {e}")

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        app.logger.info(f"Received data: {data}")

        exchange = ccxt.gemini({
            'apiKey': ‘REPLACE’WITHGEMINIAPIKEY,
            'secret': ‘REPLACEWITHGEMINISECRETKEY’,
        })

        if 'type' not in data:
            return jsonify({"error": "'type' field is required"}), 400

        if data['type'] == 'balance':
            balance = exchange.fetch_balance()
            return jsonify(balance), 200

        symbol = data.get('symbol')
        if not symbol:
            return jsonify({"error": "'symbol' field is required"}), 400

        if 'price' not in data:
            ticker = exchange.fetch_ticker(symbol)
            price = ticker['ask'] if data['type'] == 'buy' else ticker['bid']
        else:
            price = float(data['price'])

        price = round_price(price)
        order_type = data['type'].capitalize()

        if data['type'] == 'buy':
            app.logger.info("Processing buy order")
            balance = exchange.fetch_balance()
            available_balance_usd = get_available_usd(balance)

            # Use 99.8% of the available balance
            available_balance_usd *= .996

            if data['amount'] == 'ALL':
                # Calculate the maximum amount of TICKER/USD that can be bought
                amount = available_balance_usd / (price * 1)
            else:
                amount = float(data['amount'])

            # Ensure amount is above minimum order size
            if amount < 1:  # Assuming 1 share is the minimum order size
                raise Exception(f"Order amount {amount} is below the minimum order size")

            # Calculate estimated cost with 0.2% fee
            estimated_cost = price * amount * 1

            if available_balance_usd < estimated_cost:
                app.logger.error(f"Insufficient funds: {available_balance_usd} USD available, {estimated_cost} USD needed")
                return jsonify({"error": "Insufficient funds"}), 400

            # Adjust the price slightly lower to ensure it's a Maker order
            adjusted_price = round_price(price * 0.9996)

            app.logger.info(f"Placing limit buy order: symbol={symbol}, amount={amount}, price={adjusted_price}")
            
            order = execute_order_with_retry(exchange, exchange.create_limit_buy_order, symbol, amount, adjusted_price)
            app.logger.info(f"Buy order placed: {order}")

            # Start a timer to cancel all unfilled orders after 5 minutes
            threading.Timer(300, cancel_all_orders, args=(exchange,)).start()

            threading.Thread(target=delayed_send_google_form_response, args=(order_type, symbol, f"{adjusted_price:.8f}", f"{amount}", f"{estimated_cost:.2f}", exchange)).start()

        elif data['type'] == 'sell':
            app.logger.info("Processing sell order")
            balance = exchange.fetch_balance()
            REPLACEWITHTICKERSYMBOL_balance = balance['free'].get(‘REPLACEWITHTICKERSYMBOL’, 0)
            app.logger.info(f"REPLACEWITHTICKERSYMBOL balance: {REPLACEWITHTICKERSYMBOL_balance}")
            if REPLACEWITHTICKERSYMBOL_balance <= 0:
                return jsonify({"message": "No REPLACEWITHTICKERSYMBOL balance available"}), 400
            amount = REPLACEWITHTICKERSYMBOL_balance

            # Apply a 0.05% increase to the current price for the limit sell order
            adjusted_price = round_price(price * 1.0006)

            app.logger.info(f"Placing limit sell order: symbol={symbol}, amount={amount}, price={adjusted_price}")

            order = execute_order_with_retry(exchange, exchange.create_limit_sell_order, symbol, amount, adjusted_price)
            app.logger.info(f"Sell order placed: {order}")
            estimated_value = adjusted_price * amount
            threading.Thread(target=delayed_send_google_form_response, args=(order_type, symbol, f"{adjusted_price:.8f}", f"{amount}", f"{estimated_value:.2f}", exchange)).start()

        return jsonify(order), 200

    except Exception as e:
        app.logger.error(f"Error processing request: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/total_balance', methods=['POST'])
def total_balance():
    try:
        exchange = ccxt.gemini({
            'apiKey': 'REPLACE’WITHGEMINIAPIKEY’,
            'secret': 'REPLACEWITHGEMINISECRETKEY',
        })

        balance = exchange.fetch_balance()
        total_balance_usd = get_total_balance_usd(balance, exchange)
        formatted_balance = f"${total_balance_usd:,.2f}"
        return formatted_balance, 200

    except Exception as e:
        app.logger.error(f"Error fetching total balance: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)
