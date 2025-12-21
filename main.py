import json
import time
import requests
import urllib.parse
from datetime import datetime, time as dt_time, timezone, timedelta
from zoneinfo import ZoneInfo
from urllib.error import HTTPError, URLError

from config.builder import Builder
from config.config import config
from logs import logger
from presentation.observer import Observable

DATA_SLICE_DAYS = 1
DATETIME_FORMAT = "%Y-%m-%dT%H:%M"
MARKET_TIMEZONE = ZoneInfo("America/New_York")
MARKET_OPEN_TIME = dt_time(9, 30)
MARKET_CLOSE_TIME = dt_time(16, 0)


def get_dummy_data():
    # TODO: Implement functionality to provide dummy data for testing purposes.
    return []



def is_market_open(current_time):
    local_time = current_time.astimezone(MARKET_TIMEZONE)
    if local_time.weekday() >= 5:
        return False
    return MARKET_OPEN_TIME <= local_time.time() < MARKET_CLOSE_TIME


def previous_market_close(current_time):
    local_time = current_time.astimezone(MARKET_TIMEZONE)
    close_time = local_time.replace(hour=MARKET_CLOSE_TIME.hour,
                                    minute=MARKET_CLOSE_TIME.minute,
                                    second=0,
                                    microsecond=0)
    if local_time < close_time:
        close_time = close_time - timedelta(days=1)

    close_time = close_time.replace(hour=MARKET_CLOSE_TIME.hour,
                                    minute=MARKET_CLOSE_TIME.minute,
                                    second=0,
                                    microsecond=0)
    while close_time.weekday() >= 5:
        close_time = close_time - timedelta(days=1)
        close_time = close_time.replace(hour=MARKET_CLOSE_TIME.hour,
                                        minute=MARKET_CLOSE_TIME.minute,
                                        second=0,
                                        microsecond=0)
    return close_time


def fetch_prices():
    logger.info('Fetching prices')
    current_time = datetime.now(timezone.utc)
    market_closed = not is_market_open(current_time)
    timeslot_end = previous_market_close(current_time) if market_closed else current_time
    end_date = timeslot_end.strftime(DATETIME_FORMAT)
    start_data = (timeslot_end - timedelta(days=DATA_SLICE_DAYS)).strftime(DATETIME_FORMAT)
    base_url = config.data_api_base_url.rstrip('/')
    ticker = urllib.parse.quote(config.ticker, safe='')
    url = (f'{base_url}/products/{ticker}/candles?'
           f'granularity=900&start={urllib.parse.quote_plus(start_data)}&end={urllib.parse.quote_plus(end_date)}')
    headers = {"Accept": "application/json"}
    try:
        response = requests.request("GET", url, headers=headers)
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        logger.error("Failed to fetch prices from data API: %s", exc)
        return [], market_closed

    try:
        external_data = response.json()
    except json.JSONDecodeError as exc:
        logger.error("Failed to decode JSON from data API: %s", exc)
        return [], market_closed

    if not isinstance(external_data, list):
        logger.error("Unexpected data API response type: %s", type(external_data).__name__)
        return [], market_closed

    if not external_data:
        return [], market_closed

    prices = [entry[1:5] for entry in external_data[::-1]]
    return prices, market_closed


def main():
    logger.info('Initialize')

    data_sink = Observable()
    builder = Builder(config)
    builder.bind(data_sink)

    try:
        while True:
            try:
                if config.dummy_data:
                    prices = [entry[1:] for entry in get_dummy_data()]
                    payload = {"prices": prices, "market_closed": False}
                else:
                    prices, market_closed = fetch_prices()
                    payload = {"prices": prices, "market_closed": market_closed}
                data_sink.update_observers(payload)
                time.sleep(config.refresh_interval)
            except (HTTPError, URLError) as e:
                logger.error(str(e))
                time.sleep(5)
    except IOError as e:
        logger.error(str(e))
    except KeyboardInterrupt:
        logger.info('Exit')
        data_sink.close()
        exit()


if __name__ == "__main__":
    main()
