import base64
import hashlib
import json
import os

import asyncpg
from django.conf import settings
from django.utils import timezone
from utils import logger
from dotenv import load_dotenv
import requests
from utils.db.base import BaseDB

settings.configure()
load_dotenv("../.env")
SECRET_KEY = os.environ.get("CRYPTO_SECRET_KEY")


class TransferLogger(BaseDB):
    def __init__(self, db_name: str, network: str):
        super().__init__(db_name, network)

    async def create_table(self):
        conn = await asyncpg.connect(self.db_name)
        try:
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.table_name} (
                    tx_hash TEXT PRIMARY KEY,
                    token_address TEXT NOT NULL,
                    amount FLOAT NOT NULL,
                    to_address TEXT NOT NULL,
                    from_address TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    decimal INTEGER NOT NULL,
                    timestamp BIGINT NOT NULL,
                    is_used BOOLEAN NOT NULL,
                    time_added BIGINT
                )
            """)
        finally:
            await conn.close()

    async def log_transfer(self, tx_data: dict):
        timestamp = int(tx_data["timestamp"])
        time_added = int(timezone.now().timestamp())
        conn = await asyncpg.connect(self.db_name)
        try:
            await conn.execute(
                f"""
                    INSERT INTO {self.table_name} (tx_hash, token_address, amount,
                    to_address, from_address, ticker, decimal, timestamp, is_used, time_added)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)""",
                tx_data["tx_hash"],
                tx_data["token_address"],
                float(tx_data["amount"]),
                tx_data["to_address"],
                tx_data["from_address"],
                tx_data["ticker"],
                tx_data["decimal"],
                timestamp,
                False,
                time_added,
            )
            print(tx_data["decimal"])
            data = {
                "tx_hash": tx_data["tx_hash"],
                "amount": tx_data["amount"],
                "ticker": tx_data["ticker"],
                "network": tx_data["network"],
                "decimal": tx_data["decimal"]
            }
            print(data)
            json_data = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('/', '\\/')
            hash_string = base64.b64encode(json_data.encode('utf-8')).decode('utf-8') + SECRET_KEY
            sign = hashlib.md5(hash_string.encode('utf-8')).hexdigest()
            data["sign"] = sign
            response = requests.post("https://gemups.com/api/v1/payment/crypto",
                                     json=data)
            print(response.text)
        except Exception as e:
            logger.error(f"Exception while adding to db {e}")
        finally:
            await conn.close()

    async def start(self):
        await self.create_table()


# Example usage
# async def main():
#     transfer_logger = TransferLogger("transfers.db", 'optimism')
#     await transfer_logger.start()
#
#     await transfer_logger.log_transfer("0x123...", "0x456...", 1.0)
#     await transfer_logger.log_transfer("0x789...", "0x012...", 2.5)
#
#     await transfer_logger.stop()
#
#
# if __name__ == "__main__":
#     import asyncio
#
#     asyncio.run(main())
