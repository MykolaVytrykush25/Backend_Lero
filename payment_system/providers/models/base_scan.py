import httpx


class Scan:
    BASE_URL = ""
    API_KEY = ""

    def __init__(self):
        self._api_key = None
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=None))

        self.decimal = None

    async def get_transaction_history(self, **kwargs):
        raise NotImplementedError

    async def get_last_txs(self, *args, **kwargs):
        raise NotImplementedError

    async def close(self):
        await self._client.aclose()
