credentials = [
    {
        "ticker": "USDT",
        "providers": [
            {
                "to_address": [
                    "0x6C1e40f0124A229C6FBF128e95990Ef2a9181CE0"
                ],  # 0x6C1e40f0124A229C6FBF128e95990Ef2a9181CE0
                "network": "BSC",
                "token_address": "0x55d398326f99059ff775485246999027b3197955",
            },
            {
                "to_address": ["TBmmF5qJSk4CFg7MptxHMDccqqrnxSgtEN"],
                "network": "TRX",
                "token_address": "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t",
            },
            {
                "to_address": ["EBRat5pT13KSjwdw2WTmvyWsPinoFk8P2UfYzL9emeCm"],
                "network": "SOLANA",
                "token_address": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
            },
            {
                "to_address": ["0x6C1e40f0124A229C6FBF128e95990Ef2a9181CE0"],
                "network": "ETHEREUM",
                "token_address": "0xdac17f958d2ee523a2206206994597c13d831ec7",
            },
            {
                "to_address": [
                    "0x6C1e40f0124A229C6FBF128e95990Ef2a9181CE0"
                ],  # 0x6C1e40f0124A229C6FBF128e95990Ef2a9181CE0
                "network": "OPTIMISM",
                "token_address": "0x94b008aa00579c1307b0ef2c499ad98a8ce58e58",
            },
            {
                "to_address": ["UQDl6AZrOp2olNXitSwkghubhRGmYQeK_BtfRfXoOHinuLEv"],
                "network": "TON",
                "token_address": "0:148ad1a3822aee21c09a0b0a73a1e01dbbf8fb02f6c1c5e064f481249b52ace5",
            },
            {
                "to_address": ["0x6C1e40f0124A229C6FBF128e95990Ef2a9181CE0"],
                "network": "ARBITRUM",
                "token_address": "0xFd086bC7CD5C481DCC9C85ebE478A1C0b69FCbb9",
            },
            {
                "to_address": ["0x6C1e40f0124A229C6FBF128e95990Ef2a9181CE0"],
                "network": "POLYGON",
                "token_address": "0xc2132d05d31c914a87c6611c10748aeb04b58e8f",
            },
            {
                "to_address": ["0x6C1e40f0124A229C6FBF128e95990Ef2a9181CE0"],
                "network": "AVAXC",
                "token_address": "0x9702230A8Ea53601f5cD2dc00fDBc13d4dF4A8c7",
            },
        ],
    }
]


def get_wallets_and_contracts_by_network(ticker: str, network):
    for entry in credentials:
        if entry["ticker"].lower() == ticker.lower():
            for address_info in entry["providers"]:
                if network.lower() == address_info["network"].lower():
                    return address_info["to_address"][0], address_info["token_address"]
