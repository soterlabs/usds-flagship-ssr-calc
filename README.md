# usds-flagship-ssr-calc

Compute SSR (Sky Savings Rate) rewards for depositors of the [USDS Flagship Vault](https://etherscan.io/address/0xE15fcC81118895b67b6647BBd393182dF44E11E0) (Morpho Vault V2).

## How it works

1. Fetches all `Transfer` events (mints, burns, share transfers) on the vault from the Etherscan logs API
2. Fetches USDS token `Transfer` events to/from the vault to track the actual USDS balance sitting in the vault over time
3. Reconstructs each depositor's share balance over time, including pre-period balances
4. Computes rewards using each depositor's pro-rata share of the vault's USDS balance:

```
reward = (depositor_shares / total_supply) × vault_usds_balance × APR × duration / seconds_per_year
```

All events (share balance changes, vault USDS balance changes, APR boundaries) are merged into a unified timeline. Rewards are accrued for each segment between consecutive events.

## Parameters

| Parameter | Value |
|-----------|-------|
| Vault | `0xE15fcC81118895b67b6647BBd393182dF44E11E0` |
| Reward token | USDS (`0xdC035D45d973E3EC169d2276DDab16f1e407384F`) |
| APR | Configurable per period via `APR_SCHEDULE` in `constants.py` |
| Eligible balance | Actual USDS sitting in the vault (tracked via USDS Transfer events) |
| Share price | Average of start and end block prices (used for display only) |

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
| `rewards_<start>_to_<end>.json` | Airdrop file mapping depositor addresses to reward amounts (wei) |
| `depositors_summary.csv` | Detailed breakdown per depositor (balances, counts) |
| `extraction_data.json` | Intermediate data (pre-balances, share events, USDS vault events, share price) |
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
- How vault USDS balance is tracked via Transfer events
- How pre-period balances are handled
