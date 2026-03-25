"""
Compute SSR rewards per depositor from extraction data.

Uses actual vault USDS balance (tracked via USDS Transfer events) to determine
each depositor's pro-rata eligible amount, replacing the previous fixed idle factor.

Reads extraction_data.json (output of extract_events.py), computes
time-weighted rewards with variable APR, and outputs:
  - rewards_<start>_to_<end>.json: airdrop file (rewardToken + per-address amounts in wei)
  - depositors_summary.csv: detailed breakdown per depositor

Usage:
    python3 calculate_rewards.py
"""

import hashlib
import json
import os
import csv
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from constants import (
    VAULT, USDS_TOKEN, SECONDS_PER_YEAR,
    APR_SCHEDULE, REWARD_REASON,
    DEAD_ADDRESS,
)

def to_checksum_address(addr: str) -> str:
    """EIP-55 checksum encoding."""
    addr = addr.lower().removeprefix("0x")
    addr_hash = hashlib.sha3_256(addr.encode()).hexdigest()
    return "0x" + "".join(
        c.upper() if int(addr_hash[i], 16) >= 8 else c
        for i, c in enumerate(addr)
    )


D_SECONDS_PER_YEAR = Decimal(str(SECONDS_PER_YEAR))


def get_apr_at(ts):
    """Return the APR rate at a given timestamp."""
    rate = APR_SCHEDULE[0][1]
    for schedule_ts, schedule_rate in APR_SCHEDULE:
        if ts >= schedule_ts:
            rate = schedule_rate
    return rate


def compute_rewards(share_events, usds_vault_events, pre_balances,
                    initial_total_supply, initial_vault_usds,
                    start_ts, end_ts):
    """Compute rewards using actual vault USDS balance instead of a fixed idle factor.

    For each time segment:
        depositor_reward = (shares / total_supply) * vault_usds_balance * apr * duration / SECONDS_PER_YEAR

    State changes:
        - Share mint/burn events change total_supply and depositor balances
        - Share transfers change depositor balances only
        - USDS Transfer events to/from vault change vault_usds_balance
        - APR boundaries change the rate
    """
    # Global state
    total_supply = initial_total_supply
    vault_usds = initial_vault_usds

    # Per-depositor state
    balances = defaultdict(int)
    for addr, bal in pre_balances.items():
        balances[addr] = bal
    rewards = defaultdict(int)
    stats = defaultdict(lambda: {"deposited": 0, "withdrawn": 0, "dep_count": 0, "wdr_count": 0})

    # Build unified timeline
    timeline = []
    for e in share_events:
        timeline.append((max(e["timestamp"], start_ts), e["block_number"], e["log_index"], "share", e))
    for e in usds_vault_events:
        timeline.append((max(e["timestamp"], start_ts), e["block_number"], e["log_index"], "usds", e))
    for rate_ts, _ in APR_SCHEDULE:
        if start_ts < rate_ts < end_ts:
            timeline.append((rate_ts, 0, 0, "apr", None))

    timeline.sort(key=lambda x: x[:4])

    last_ts = start_ts

    def accrue(up_to_ts):
        """Accrue rewards for all depositors for segment [last_ts, up_to_ts)."""
        nonlocal last_ts
        if up_to_ts <= last_ts or total_supply <= 0:
            last_ts = up_to_ts
            return
        apr = get_apr_at(last_ts)
        duration = Decimal(up_to_ts - last_ts)
        d_vault_usds = Decimal(vault_usds)
        d_total_supply = Decimal(total_supply)
        d_apr = Decimal(str(apr))
        for addr, bal in balances.items():
            if bal > 0:
                reward = int(
                    Decimal(bal) * d_vault_usds * d_apr * duration
                    / (d_total_supply * D_SECONDS_PER_YEAR)
                )
                rewards[addr] += reward
        last_ts = up_to_ts

    for ts, _bn, _li, event_type, event in timeline:
        if ts > end_ts:
            break
        accrue(ts)
        if event_type == "share":
            addr = event["address"]
            delta = event["delta_shares"]
            balances[addr] += delta
            if event["type"] == "deposit":
                total_supply += delta
                stats[addr]["deposited"] += delta
                stats[addr]["dep_count"] += 1
            elif event["type"] == "withdraw":
                total_supply += delta  # delta is negative
                stats[addr]["withdrawn"] += abs(delta)
                stats[addr]["wdr_count"] += 1
        elif event_type == "usds":
            vault_usds += event["delta_usds"]

    # Final segment
    accrue(end_ts)

    # Build results
    results = {}
    all_addrs = set(balances.keys()) | set(rewards.keys())
    for addr in all_addrs:
        if addr == DEAD_ADDRESS:
            continue
        reward_wei = rewards.get(addr, 0)
        balance = balances.get(addr, 0)
        if reward_wei <= 0 and balance <= 0:
            continue
        s = stats[addr]
        results[addr] = {
            "reward_wei": reward_wei,
            "final_balance_shares": balance,
            "initial_balance_shares": pre_balances.get(addr, 0),
            "total_deposited_shares": s["deposited"],
            "total_withdrawn_shares": s["withdrawn"],
            "deposit_count": s["dep_count"],
            "withdraw_count": s["wdr_count"],
        }

    return results


def main():
    out_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(out_dir, "extraction_data.json")

    if not os.path.exists(data_path):
        raise RuntimeError(f"Run extract_events.py first — {data_path} not found")

    with open(data_path) as f:
        data = json.load(f)

    avg_price = data["avg_share_price"]
    initial_total_supply = int(data["initial_total_supply"])
    initial_vault_usds = int(data["initial_vault_usds"])
    pre_balances = {k: int(v) for k, v in data["pre_balances"].items()}

    share_events = []
    for e in data["events"]:
        share_events.append({
            "address": e["address"],
            "delta_shares": int(e["delta_shares"]),
            "type": e["type"],
            "block_number": e["block_number"],
            "log_index": e["log_index"],
            "timestamp": e["timestamp"],
            "tx_hash": e["tx_hash"],
        })

    usds_vault_events = []
    for e in data.get("usds_vault_events", []):
        usds_vault_events.append({
            "delta_usds": int(e["delta_usds"]),
            "block_number": e["block_number"],
            "log_index": e["log_index"],
            "timestamp": e["timestamp"],
            "tx_hash": e["tx_hash"],
        })

    print(f"Vault: {VAULT}")
    print(f"Loaded {len(share_events)} share events, {len(usds_vault_events)} USDS vault events, {len(pre_balances)} pre-period balances")
    print(f"Share price: {avg_price:.10f} USDS/share")
    print(f"Initial total supply: {initial_total_supply / 1e18:,.2f} shares")
    print(f"Initial vault USDS:   {initial_vault_usds / 1e18:,.2f} USDS")
    print(f"Effective idle ratio:  {initial_vault_usds / (initial_total_supply * avg_price):.4f}")
    print(f"APR schedule: {[(f'{rate*100:.2f}%') for _, rate in APR_SCHEDULE]}")
    print()

    start_ts = data["from_block_ts"]
    end_ts = data["to_block_ts"]
    total_seconds = end_ts - start_ts
    total_days = total_seconds / 86400
    print(f"Period: {datetime.fromtimestamp(start_ts, tz=timezone.utc)} to {datetime.fromtimestamp(end_ts, tz=timezone.utc)}")
    print(f"Duration: {total_days:.2f} days ({total_seconds:,} seconds)")
    print()

    results = compute_rewards(share_events, usds_vault_events, pre_balances,
                              initial_total_supply, initial_vault_usds,
                              start_ts, end_ts)
    sorted_results = sorted(results.items(), key=lambda x: x[1]["reward_wei"], reverse=True)

    total_rewards = sum(v["reward_wei"] for v in results.values())
    print(f"Unique depositors: {len(sorted_results)}")
    print(f"Total rewards: {total_rewards / 1e18:,.6f} USDS")
    print()

    # Top depositors
    print("Top depositors by reward:")
    for addr, v in sorted_results[:15]:
        bal_usds = v["final_balance_shares"] * avg_price / 1e18
        print(f"  {addr}  reward={v['reward_wei']/1e18:>12,.6f}  "
              f"bal={bal_usds:>14,.2f}  ({v['deposit_count']}d/{v['withdraw_count']}w)")

    # Write depositor summary CSV
    summary_path = os.path.join(out_dir, "depositors_summary.csv")
    with open(summary_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "depositor", "reward_wei", "reward_usds",
            "initial_balance_shares", "final_balance_shares", "final_balance_usds",
            "total_deposited_shares", "total_withdrawn_shares",
            "deposit_count", "withdraw_count",
        ])
        for addr, v in sorted_results:
            writer.writerow([
                addr, v["reward_wei"], f"{v['reward_wei'] / 1e18:.6f}",
                v["initial_balance_shares"], v["final_balance_shares"],
                f"{v['final_balance_shares'] * avg_price / 1e18:.6f}",
                v["total_deposited_shares"], v["total_withdrawn_shares"],
                v["deposit_count"], v["withdraw_count"],
            ])
    print(f"\nWrote {len(sorted_results)} depositors to {summary_path}")

    # Write rewards JSON
    rewards_json = {
        "rewardToken": USDS_TOKEN,
        "rewards": {}
    }
    for addr, v in sorted_results:
        if v["reward_wei"] > 0:
            rewards_json["rewards"][to_checksum_address(addr)] = {
                REWARD_REASON: str(v["reward_wei"])
            }

    # Dated filename: rewards_YYYY-MM-DD_to_YYYY-MM-DD.json
    start_date = datetime.fromtimestamp(start_ts, tz=timezone.utc).strftime("%Y-%m-%d")
    end_date = datetime.fromtimestamp(end_ts, tz=timezone.utc).strftime("%Y-%m-%d")
    rewards_filename = f"rewards_{start_date}_to_{end_date}.json"
    rewards_path = os.path.join(out_dir, rewards_filename)
    with open(rewards_path, "w") as f:
        json.dump(rewards_json, f, indent=2)
    print(f"Wrote {len(rewards_json['rewards'])} rewards to {rewards_path}")

    print(f"\nShare price used: {avg_price:.10f} USDS/share (average of start and end)")
    print(f"Total rewards to distribute: {total_rewards / 1e18:,.6f} USDS ({total_rewards} wei)")


if __name__ == "__main__":
    main()
