"""
Compute SSR rewards per depositor from extraction data.

Reads extraction_data.json (output of extract_events.py), computes
time-weighted rewards with variable APR, and outputs:
  - rewards.json: airdrop file (rewardToken + per-address amounts in wei)
  - depositors_summary.csv: detailed breakdown per depositor

Usage:
    python3 calculate_rewards.py
"""

import json
import os
import csv
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from constants import (
    VAULT, FROM_BLOCK_TS, IDLE_FACTOR, SECONDS_PER_YEAR,
    APR_SCHEDULE, REWARD_TOKEN, REWARD_REASON,
    DEAD_ADDRESS,
)

# Convert float constants to Decimal for precise arithmetic
D_IDLE_FACTOR = Decimal(str(IDLE_FACTOR))
D_SECONDS_PER_YEAR = Decimal(str(SECONDS_PER_YEAR))


def get_apr_at(ts):
    """Return the APR rate at a given timestamp."""
    rate = APR_SCHEDULE[0][1]
    for schedule_ts, schedule_rate in APR_SCHEDULE:
        if ts >= schedule_ts:
            rate = schedule_rate
    return rate


def _accrue_segment(balance, avg_price, apr, duration):
    """Compute reward wei for a single time segment using Decimal arithmetic."""
    return int(Decimal(balance) * avg_price * D_IDLE_FACTOR * Decimal(str(apr)) * duration / D_SECONDS_PER_YEAR)


def compute_rewards(events, pre_balances, start_ts, end_ts, avg_price_float):
    """Compute rewards for each depositor based on time-weighted balance and variable APR.

    reward = sum over each time segment of:
        balance_shares * avg_price * IDLE_FACTOR * apr * segment_duration / SECONDS_PER_YEAR

    Balance changes happen at event timestamps. APR changes at rate boundaries.
    Rate boundaries are injected into the timeline so each segment has a single APR.
    """
    avg_price = Decimal(str(avg_price_float))

    # Group events by address
    by_addr = defaultdict(list)
    for e in events:
        by_addr[e["address"]].append(e)

    # Include addresses with pre-period balances
    for addr in pre_balances:
        if addr not in by_addr:
            by_addr[addr] = []

    # Rate change timestamps (boundaries where we must split segments)
    rate_boundaries = [ts for ts, _ in APR_SCHEDULE if start_ts < ts < end_ts]

    results = {}

    for addr, addr_events in by_addr.items():
        addr_events.sort(key=lambda e: (e["block_number"], e["log_index"]))

        balance = pre_balances.get(addr, 0)
        reward_wei = 0
        last_ts = start_ts
        total_deposited_shares = 0
        total_withdrawn_shares = 0
        deposit_count = 0
        withdraw_count = 0

        # Merge event timestamps and rate boundaries into a single timeline.
        # Since rate boundaries are always present, each segment [last_ts, target_ts)
        # is guaranteed to have a single APR — no inner splitting needed.
        all_timestamps = sorted(set(
            [max(e["timestamp"], start_ts) for e in addr_events] + rate_boundaries
        ))

        event_idx = 0

        for target_ts in all_timestamps:
            if target_ts > end_ts:
                break

            # Accumulate reward for segment [last_ts, target_ts) at current balance and rate
            if target_ts > last_ts and balance > 0:
                apr = get_apr_at(last_ts)
                duration = Decimal(target_ts - last_ts)
                reward_wei += _accrue_segment(balance, avg_price, apr, duration)

            last_ts = target_ts

            # Apply all events at this timestamp
            while event_idx < len(addr_events):
                e = addr_events[event_idx]
                e_ts = max(e["timestamp"], start_ts)
                if e_ts > target_ts:
                    break
                balance += e["delta_shares"]
                if e["type"] == "deposit":
                    total_deposited_shares += e["delta_shares"]
                    deposit_count += 1
                elif e["type"] == "withdraw":
                    total_withdrawn_shares += abs(e["delta_shares"])
                    withdraw_count += 1
                event_idx += 1

        # Final segment [last_ts, end_ts]
        if end_ts > last_ts and balance > 0:
            apr = get_apr_at(last_ts)
            duration = Decimal(end_ts - last_ts)
            reward_wei += _accrue_segment(balance, avg_price, apr, duration)

        # Skip dead address and zero rewards
        if addr == DEAD_ADDRESS:
            continue
        if reward_wei <= 0 and balance <= 0:
            continue

        results[addr] = {
            "reward_wei": reward_wei,
            "final_balance_shares": balance,
            "initial_balance_shares": pre_balances.get(addr, 0),
            "total_deposited_shares": total_deposited_shares,
            "total_withdrawn_shares": total_withdrawn_shares,
            "deposit_count": deposit_count,
            "withdraw_count": withdraw_count,
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
    pre_balances = {k: int(v) for k, v in data["pre_balances"].items()}
    events = []
    for e in data["events"]:
        events.append({
            "address": e["address"],
            "delta_shares": int(e["delta_shares"]),
            "type": e["type"],
            "block_number": e["block_number"],
            "log_index": e["log_index"],
            "timestamp": e["timestamp"],
            "tx_hash": e["tx_hash"],
        })

    print(f"Vault: {VAULT}")
    print(f"Loaded {len(events)} events, {len(pre_balances)} pre-period balances")
    print(f"Share price: {avg_price:.10f} USDS/share")
    print(f"Idle factor: {IDLE_FACTOR}")
    print(f"APR schedule: {[(f'{rate*100:.2f}%') for _, rate in APR_SCHEDULE]}")
    print()

    start_ts = data["from_block_ts"]
    end_ts = data["to_block_ts"]
    total_seconds = end_ts - start_ts
    total_days = total_seconds / 86400
    print(f"Period: {datetime.fromtimestamp(start_ts, tz=timezone.utc)} to {datetime.fromtimestamp(end_ts, tz=timezone.utc)}")
    print(f"Duration: {total_days:.2f} days ({total_seconds:,} seconds)")
    print()

    results = compute_rewards(events, pre_balances, start_ts, end_ts, avg_price)
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
        "rewardToken": REWARD_TOKEN,
        "rewards": {}
    }
    for addr, v in sorted_results:
        if v["reward_wei"] > 0:
            rewards_json["rewards"][addr] = {
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
