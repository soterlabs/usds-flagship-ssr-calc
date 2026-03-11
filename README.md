# usds-flagship-ssr-calc

Compute SSR (Sky Savings Rate) rewards for depositors of the [USDS Flagship Vault](https://etherscan.io/address/0xE15fcC81118895b67b6647BBd393182dF44E11E0) (Morpho Vault V2).

## How it works

1. Fetches all `Transfer` events (mints, burns, share transfers) on the vault from the Etherscan logs API
2. Reconstructs each depositor's share balance over time, including pre-period balances
3. Computes rewards using time-weighted share balances, converted to USDS via the vault's share price:

```
reward = balance_shares × share_price × idle_factor × APR × duration / seconds_per_year
```

Segments are split at every balance change and at the APR change boundary.

## Parameters

| Parameter | Value |
|-----------|-------|
| Vault | `0xE15fcC81118895b67b6647BBd393182dF44E11E0` |
| Reward token | USDS (`0xdC035D45d973E3EC169d2276DDab16f1e407384F`) |
| Period start | Block 24577985 (2026-03-03 16:00:59 UTC) |
| Period end | Block 24628118 (2026-03-10 16:00:00 UTC) |
| APR (before block 24621023) | 4.00% |
| APR (from block 24621023) | 3.75% |
| Idle factor | 80% (only idle vault deposits are rewarded, ~20% is allocated to markets) |
| Share price | Average of start and end block prices |

## Usage

```bash
export RPC_URL="https://eth-mainnet.g.alchemy.com/v2/YOUR_KEY"
export ETHERSCAN_API_KEY="YOUR_KEY"

# Step 1: Extract events from on-chain data
python3 extract_events.py

# Step 2: Compute rewards from extracted data
python3 calculate_rewards.py
```

No dependencies required (Python 3.7+ standard library only).

## Output

| File | Description |
|------|-------------|
| `rewards.json` | Airdrop file mapping depositor addresses to reward amounts (wei) |
| `depositors_summary.csv` | Detailed breakdown per depositor (TWA, balances, counts) |
| `extraction_data.json` | Intermediate data (pre-balances, events, share price) |
| `events.csv` | Raw share transfer events used for computation |

### rewards.json format

```json
{
  "rewardToken": "0xdC035D45d973E3EC169d2276DDab16f1e407384F",
  "rewards": {
    "0xee2826453a4fd5afeb7ceffeef3ffa2320081268": {
      "usds-flagship-ssr": "7768600710..."
    }
  }
}
```

## Methodology

See [PLAN.md](PLAN.md) for the full methodology, including:
- Why shares are tracked instead of assets
- How the 80% idle factor was verified on-chain
- How pre-period balances are handled
