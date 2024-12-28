#!/usr/bin/env python3

import argparse
import asyncio
import os
import random
import time

from config import credentials
from dotenv import load_dotenv
from utils import logger
from utils.db.db_logger import TransferLogger

from providers.okx_wallet import OkxWallet

load_dotenv()


class Web3Scan:
    def __init__(self):
        self.db_path = os.getenv("DB_TRANSFERS_ROUTE")
        self.credentials = credentials
        self.networks = {"bsc": OkxWallet()}

    async def logging_db(self, amount: float):
        tx_data = {
            "tx_hash": f"0x__test__{random.randint(0, 9999999999)}__test__",
            "token_address": "0x55d398326f99059ff775485246999027b3197955",
            "amount": str(int(amount * 10**6)),
            "to_address": "0x6c1e40f0124a229c6fbf128e95990ef2a9181ce0",
            "from_address": "0x4a1c6b0ee2fc2fe4b957ca791b66839e382f8776",
            "ticker": "USDT",
            "decimal": 6,
            "timestamp": int(time.time() * 1000),
            "network": "BSC",
        }
        network_name = tx_data["network"]

        transfer_logger = TransferLogger(self.db_path, network_name)
        await transfer_logger.start()
        logger.info(f"ADDING {tx_data}")
        await transfer_logger.log_transfer(tx_data)
        await transfer_logger.stop()


async def main(amount: float):
    web3_scan = Web3Scan()
    await web3_scan.logging_db(amount)


if __name__ == "__main__":  # python3 one_pay.py --amount 1
    parser = argparse.ArgumentParser(description="Web3Scan Logging Script")
    parser.add_argument("--amount", type=float, required=True, help="Amount to log")

    args = parser.parse_args()

    asyncio.run(main(args.amount))
