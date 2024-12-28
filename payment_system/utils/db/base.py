class BaseDB:
    def __init__(self, db_name: str, network: str):
        self.db_name = db_name
        self.table_name = network
        self.conn = None

    async def stop(self):
        if self.conn:
            await self.conn.close()
