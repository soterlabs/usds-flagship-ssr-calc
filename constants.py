# Vault
VAULT = "0xE15fcC81118895b67b6647BBd393182dF44E11E0"

# ERC20 Transfer event topic
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# Period start: 2026-03-24 16:00:11 UTC
FROM_BLOCK = 24728449
FROM_BLOCK_TS = 1774368011

# Period end: 2026-03-31 16:00:11 UTC (~1 week)
TO_BLOCK = 24778643
TO_BLOCK_TS = 1774972811

# Token config
USDS_TOKEN = "0xdC035D45d973E3EC169d2276DDab16f1e407384F"  # USDS ERC20
DEAD_ADDRESS = "0x000000000000000000000000000000000000dead"
ZERO_ADDR_PADDED = "0x" + "0" * 64

# Reward parameters
SECONDS_PER_YEAR = 365.25 * 24 * 3600

# APR schedule: constant 3.75% for this period
APR_SCHEDULE = [
    (FROM_BLOCK_TS, 0.0375),  # 3.75% for the full period
]

# Output format
REWARD_REASON = "usds-flagship-ssr"

# APIs
ETHERSCAN_API = "https://api.etherscan.io/v2/api"
