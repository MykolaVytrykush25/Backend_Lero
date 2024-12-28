import os

from config import credentials
from dotenv import load_dotenv
from utils import logger
from utils.db.db_logger import TransferLogger

from providers.okx_wallet import OkxWallet

load_dotenv("../.env")


class Web3Scan:
    def __init__(self):
        self.db_path = os.getenv("DB_TRANSFERS_ROUTE")

        self.credentials = credentials

        self.network_provider = OkxWallet()

    async def logging_db(self, last_block: int = 0):
        network_name = ""
        while True:
            try:
                txs_resp = await self.network_provider.get_last_txs(last_block)
                logger.info(txs_resp)

                if txs := txs_resp["txs"]:
                    last_block = int(txs_resp["last_block"]) + 1

                for tx_data in txs:
                    network_name = tx_data["network"]
                    transfer_logger = TransferLogger(self.db_path, network_name)

                    await transfer_logger.start()
                    await transfer_logger.log_transfer(tx_data)
                    await transfer_logger.stop()
            except Exception as e:
                import traceback

                logger.error(f"{network_name} | {e} | {traceback.format_exc()}")

            await asyncio.sleep(10)

    # async def start_logging(self):
    #     tasks = []
    #     for name, network in self.providers.items():
    #         tasks.append(asyncio.create_task(self.logging_db(network)))
    #
    #     await asyncio.gather(*tasks)


async def main():
    web3_scan = Web3Scan()
    await web3_scan.logging_db()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
