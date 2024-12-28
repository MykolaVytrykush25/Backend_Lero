import asyncio
import time

from config import get_wallets_and_contracts_by_network
from tenacity import retry, stop_after_attempt, wait_fixed
from utils import logger

from .models.base_scan import Scan


class OkxWallet(Scan):
    tokens_ids = {
        "USDT": {
            "BSC": 5004,
            "TRX": 813,
            "OPTIMISM": 10005,
            "ARBITRUM": 9001,
            "POLYGON": 6201,
            "AVAXC": 7003,
            "ETHEREUM": 818,
            # "APTOS": 351628,
            "SOLANA": 2647,
            "TON": 28003,
        }
    }

    def __init__(self):
        super().__init__()

    async def get_last_txs(self, last_block: int = 0):
        res_json = await self.get_wallet_history(last_block)
        print(res_json)
        formatted_txs = []
        network = None
        if txs := res_json.get("data", {}).get("content", []):
            for tx in txs:
                asset_change = tx["assetChange"][0]
                if network := get_key_by_value(OkxWallet.tokens_ids, asset_change["coinId"]):
                    wallet, token_address = get_wallets_and_contracts_by_network("USDT", network)
                    if asset_change["direction"] == 1:  # if == 1 then deposit
                        if tx["address"].lower() == wallet.lower():
                            formatted_txs.append(
                                {
                                    "tx_hash": tx["txhash"],
                                    "token_address": token_address,
                                    "amount": asset_change["coinAmount"],
                                    "to_address": tx["to"],
                                    "from_address": tx["from"],
                                    "ticker": asset_change["coinSymbol"],
                                    "decimal": asset_change["vdecimalNum"],
                                    "timestamp": tx["txTime"],
                                    "network": network,
                                }
                            )
            if formatted_txs:
                last_block = formatted_txs[0]["timestamp"]
        return {"txs": formatted_txs, "network": network, "last_block": last_block}

    @retry(
        stop=stop_after_attempt(7),
        wait=wait_fixed(2),
        before_sleep=lambda retry_state, **kwargs: logger.info(f"Retrying... {retry_state.outcome.exception()}"),
        reraise=True,
    )
    async def get_wallet_history(self, last_block: int = 0, limit: int = 5):
        url = "https://wallet.okex.org/priapi/v1/wallet/tx/order/list"  # wallet.okx.com # old

        json_data = {
            "lastRowId": "",
            "limit": limit,
            "accountIds": [
                "D6733685-0666-4F78-B1E3-02DD6A24B5FC",
            ],
            "startDate": last_block,
            "endDate": time.time() * 10**3,
            "mainCoinId": "",
            "status": [
                1,
                2,
                3,
                4,
            ],
            "hideValuelessNft": True,
        }

        response = await self._client.post(url, json=json_data)

        return response.json()


def get_key_by_value(tokens_ids, value):
    for token, networks in tokens_ids.items():
        for network, id_ in networks.items():
            if id_ == value:
                return network
    return None
