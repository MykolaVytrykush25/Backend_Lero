import logging

import psycopg2
from django.conf import settings

logger = logging.getLogger(__name__)
import os
from decimal import Decimal, getcontext

from dotenv import load_dotenv

load_dotenv()


class BaseDB:
    def __init__(self, db_name: str, network: str):
        self.db_name = db_name
        self.table_name = network
        self.conn = None

    def stop(self):
        if self.conn:
            self.conn.close()


class Payment(BaseDB):
    def __init__(self, db_name: str, network: str):
        super().__init__(db_name, network)
        self.credentials = settings.CREDENTIALS

    def full_decimal(self, amount: float, decimal: int):
        getcontext().prec = 21  # maximum of precision number
        float_value = Decimal(str(amount))
        scale_factor = Decimal("10") ** decimal

        result = float_value * scale_factor

        return int(result)

    def get_token_info(self, network: str, ticker: str):
        for entry in self.credentials:
            if entry["ticker"].lower() == ticker.lower():
                for address_info in entry["networks"]:
                    if network.lower() == address_info["network"].lower():
                        return "", address_info["token_address"]

        raise Exception("Token not found! Check config.py")

    def get_token_pay_address(self, network: str, ticker: str):
        if not ticker:
            raise ValueError("Ticker cannot be None or empty.")

        if not network:
            raise ValueError("Network cannot be None or empty.")

        for entry in self.credentials:
            if entry["ticker"].lower() == ticker.lower():
                for address_info in entry["networks"]:
                    if network.lower() == address_info["network"].lower():
                        return address_info["to_address"][0]

        error_message = f"Payment address not found for ticker '{ticker}' on network '{network}'."
        logger.error(error_message)

        return None

    def get_cryptocurrencies(self):
        result = []
        for entry in self.credentials:
            currency = {"ticker": entry["ticker"], "networks": []}
            for address_info in entry["networks"]:
                currency["networks"].append(
                    {"address": address_info["to_address"][0], "network": address_info["network"]}
                )
            result.append(currency)

        return result

    def change_status(self, cursor, row, db):
        cursor.execute(
            f"""
                UPDATE {self.table_name}
                SET is_used = TRUE
                WHERE tx_hash = %s
            """,
            (row[0],),
        )
        logger.info("status changing to used (transfers)")
        db.commit()

    def check(self, amount: float, ticker: str, date_created=None, range_allowed=False):
        _, token_address = self.get_token_info(self.table_name, ticker)
        logger.info(
            f"PAYMENT.CHECKER, =========== {amount}, {ticker}"
            f" token_address={token_address} timestamp={date_created}"
        )
        with psycopg2.connect(os.getenv("DB_TRANSFERS_ROUTE")) as db:
            # logger.info(f"CURSOR BEFORE EXECUTING range_allowed {range_allowed}")
            cursor = db.cursor()
            cursor.execute(
                f"""
                    SELECT tx_hash, decimal, amount
                    FROM {self.table_name}
                    WHERE token_address = %s  AND is_used = FALSE AND timestamp >= %s
                """,
                (token_address, date_created),
            )
            rows = cursor.fetchall()
            for row in rows:
                tx_hash, decimal_value, amount_query = row
                if range_allowed:
                    if (
                        self.full_decimal(amount * 0.98, decimal_value)
                        <= amount_query
                        <= self.full_decimal(amount * 1.03, decimal_value)
                    ):
                        self.change_status(cursor, row, db)
                        return True
                else:
                    if amount_query == self.full_decimal(amount, decimal_value):
                        self.change_status(cursor, row, db)
                        logger.info(f"true, {amount_query} == {self.full_decimal(amount, decimal_value)}")
                        return True

        return False
