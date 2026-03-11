"""
Extract share transfer events (deposits, withdrawals, transfers) from the
Flagship vault and compute pre-period balances.

Outputs:
  - events.csv: all in-period share transfer events
  - balances.json: pre-period balances + in-period events (intermediate data for calculate_rewards.py)

Usage:
    python3 extract_events.py

Requires ETHERSCAN_API_KEY and RPC_URL env vars.
"""

import json
import os
import csv
import urllib.request
import time
from collections import defaultdict
from datetime import datetime, timezone

from constants import (
    VAULT, TRANSFER_TOPIC, FROM_BLOCK, FROM_BLOCK_TS,
    TO_BLOCK, TO_BLOCK_TS,
    USDS_DECIMALS, ZERO_ADDR_PADDED, DEAD_ADDRESS, ETHERSCAN_API,
)

ETHERSCAN_API_KEY = os.environ.get("ETHERSCAN_API_KEY", "")
RPC_URL = os.environ.get("RPC_URL", "")


def etherscan_get_logs(topic0, from_block, to_block, page=1, offset=1000):
    params = (
        f"?chainid=1&module=logs&action=getLogs"
        f"&address={VAULT}"
        f"&topic0={topic0}"
        f"&fromBlock={from_block}"
        f"&toBlock={to_block}"
        f"&page={page}"
        f"&offset={offset}"
        f"&apikey={ETHERSCAN_API_KEY}"
    )
    url = ETHERSCAN_API + params
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"HTTP {e.code}: {body}")


def fetch_all_logs(topic0, label, from_block=FROM_BLOCK):
    all_logs = []
    page = 1
    while True:
        print(f"  [{label}] Fetching page {page}...")
        result = etherscan_get_logs(topic0, from_block, 99999999, page=page)

        if result.get("status") == "0":
            break

        if result.get("status") != "1":
            raise RuntimeError(f"Etherscan error: {result}")

        logs = result["result"]
        all_logs.extend(logs)
        print(f"    Got {len(logs)} events (total: {len(all_logs)})")

        if len(logs) < 1000:
            break
        page += 1
        time.sleep(0.25)

    return all_logs


def rpc_call(method, params):
    payload = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    req = urllib.request.Request(RPC_URL, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
    if "error" in result:
        raise RuntimeError(f"RPC error: {result['error']}")
    return result["result"]


def get_share_price_at_block(block_hex):
    """Get totalAssets/totalSupply at a given block to convert shares -> USDS."""
    ta_result = rpc_call("eth_call", [{"to": VAULT, "data": "0x01e1d114"}, block_hex])
    total_assets = int(ta_result, 16)
    ts_result = rpc_call("eth_call", [{"to": VAULT, "data": "0x18160ddd"}, block_hex])
    total_supply = int(ts_result, 16)
    return total_assets, total_supply


def parse_transfer_events(logs):
    """Parse Transfer events into share balance changes per address."""
    events = []
    for log in logs:
        from_addr = log["topics"][1]
        to_addr = log["topics"][2]
        shares = int(log["data"], 16)
        block_number = int(log["blockNumber"], 16)
        log_index = int(log["logIndex"], 16)
        timestamp = int(log["timeStamp"], 16)
        tx_hash = log["transactionHash"]

        is_mint = from_addr == ZERO_ADDR_PADDED
        is_burn = to_addr == ZERO_ADDR_PADDED

        if is_mint:
            to = "0x" + to_addr[26:]
            events.append({
                "address": to.lower(), "delta_shares": shares,
                "type": "deposit", "block_number": block_number,
                "log_index": log_index, "timestamp": timestamp, "tx_hash": tx_hash,
            })
        elif is_burn:
            frm = "0x" + from_addr[26:]
            events.append({
                "address": frm.lower(), "delta_shares": -shares,
                "type": "withdraw", "block_number": block_number,
                "log_index": log_index, "timestamp": timestamp, "tx_hash": tx_hash,
            })
        else:
            frm = "0x" + from_addr[26:]
            to = "0x" + to_addr[26:]
            events.append({
                "address": frm.lower(), "delta_shares": -shares,
                "type": "transfer_out", "block_number": block_number,
                "log_index": log_index, "timestamp": timestamp, "tx_hash": tx_hash,
            })
            events.append({
                "address": to.lower(), "delta_shares": shares,
                "type": "transfer_in", "block_number": block_number,
                "log_index": log_index, "timestamp": timestamp, "tx_hash": tx_hash,
            })

    return events


def get_pre_period_balances(transfer_logs_pre):
    """Compute share balances at the start of the period from pre-period Transfer events."""
    balances = defaultdict(int)
    for log in transfer_logs_pre:
        from_addr = log["topics"][1]
        to_addr = log["topics"][2]
        shares = int(log["data"], 16)

        if from_addr != ZERO_ADDR_PADDED:
            frm = "0x" + from_addr[26:]
            balances[frm.lower()] -= shares
        if to_addr != ZERO_ADDR_PADDED:
            to = "0x" + to_addr[26:]
            balances[to.lower()] += shares

    return balances


def main():
    if not ETHERSCAN_API_KEY:
        raise RuntimeError("Set ETHERSCAN_API_KEY env var")
    if not RPC_URL:
        raise RuntimeError("Set RPC_URL env var")

    print(f"Vault: {VAULT}")
    print(f"From block: {FROM_BLOCK} (start)")
    print(f"To block:   {TO_BLOCK} (end)")
    print()

    # Verify block timestamps match constants
    print("Verifying block timestamps...")
    start_block_ts = int(rpc_call("eth_getBlockByNumber", [hex(FROM_BLOCK), False])["timestamp"], 16)
    end_block_ts = int(rpc_call("eth_getBlockByNumber", [hex(TO_BLOCK), False])["timestamp"], 16)
    if start_block_ts != FROM_BLOCK_TS:
        raise RuntimeError(f"FROM_BLOCK_TS mismatch: constant={FROM_BLOCK_TS}, actual={start_block_ts}")
    if end_block_ts != TO_BLOCK_TS:
        raise RuntimeError(f"TO_BLOCK_TS mismatch: constant={TO_BLOCK_TS}, actual={end_block_ts}")
    print(f"  FROM_BLOCK timestamp verified: {FROM_BLOCK_TS}")
    print(f"  TO_BLOCK timestamp verified:   {TO_BLOCK_TS}")
    print()

    # Get share price at start and end
    print("Fetching share price at start block...")
    start_ta, start_ts = get_share_price_at_block(hex(FROM_BLOCK))
    start_price = start_ta / start_ts if start_ts > 0 else 1.0
    print(f"  Start: totalAssets={start_ta/1e18:,.2f}, totalSupply={start_ts/1e18:,.2f}, price={start_price:.10f}")

    print("Fetching share price at end block...")
    end_ta, end_ts = get_share_price_at_block(hex(TO_BLOCK))
    end_price = end_ta / end_ts if end_ts > 0 else 1.0
    print(f"  End:   totalAssets={end_ta/1e18:,.2f}, totalSupply={end_ts/1e18:,.2f}, price={end_price:.10f}")

    avg_price = (start_price + end_price) / 2
    print(f"  Avg price: {avg_price:.10f} USDS/share")
    print()

    # Fetch pre-period Transfer events
    print("Fetching pre-period Transfer events...")
    pre_transfer_logs = fetch_all_logs(TRANSFER_TOPIC, "Pre-Transfer", from_block=0)
    pre_transfer_logs = [l for l in pre_transfer_logs if int(l["blockNumber"], 16) < FROM_BLOCK]
    print(f"Pre-period Transfer events: {len(pre_transfer_logs)}")
    pre_balances = get_pre_period_balances(pre_transfer_logs)
    non_zero_pre = {k: v for k, v in pre_balances.items() if v > 0 and k != DEAD_ADDRESS}
    print(f"Addresses with pre-period balance: {len(non_zero_pre)}")
    for addr, bal in sorted(non_zero_pre.items(), key=lambda x: -x[1]):
        print(f"  {addr}: {bal/1e18:,.2f} shares ({bal/1e18 * avg_price:,.2f} USDS)")
    print()

    # Fetch in-period Transfer events
    print("Fetching in-period Transfer events...")
    transfer_logs = fetch_all_logs(TRANSFER_TOPIC, "Transfer")
    transfer_logs = [l for l in transfer_logs
                     if FROM_BLOCK <= int(l["blockNumber"], 16)
                     and int(l["timeStamp"], 16) <= TO_BLOCK_TS]
    print(f"In-period Transfer events: {len(transfer_logs)}")

    events = parse_transfer_events(transfer_logs)
    events.sort(key=lambda e: (e["block_number"], e["log_index"]))

    type_counts = defaultdict(int)
    for e in events:
        type_counts[e["type"]] += 1
    print(f"  Deposits: {type_counts['deposit']}, Withdrawals: {type_counts['withdraw']}, "
          f"Transfers out: {type_counts['transfer_out']}, Transfers in: {type_counts['transfer_in']}")
    print()

    # Write events CSV
    out_dir = os.path.dirname(os.path.abspath(__file__))
    events_path = os.path.join(out_dir, "events.csv")
    with open(events_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["block_number", "log_index", "timestamp", "type", "address", "delta_shares", "tx_hash"])
        for e in events:
            writer.writerow([
                e["block_number"], e["log_index"],
                datetime.fromtimestamp(e["timestamp"], tz=timezone.utc).isoformat(),
                e["type"], e["address"], e["delta_shares"], e["tx_hash"],
            ])
    print(f"Wrote {len(events)} events to {events_path}")

    # Write intermediate data for calculate_rewards.py
    data_path = os.path.join(out_dir, "extraction_data.json")
    # Convert pre_balances (int keys) to serializable format
    serializable_pre = {k: str(v) for k, v in pre_balances.items() if v > 0}
    serializable_events = []
    for e in events:
        serializable_events.append({
            "address": e["address"],
            "delta_shares": str(e["delta_shares"]),
            "type": e["type"],
            "block_number": e["block_number"],
            "log_index": e["log_index"],
            "timestamp": e["timestamp"],
            "tx_hash": e["tx_hash"],
        })

    extraction = {
        "vault": VAULT,
        "from_block": FROM_BLOCK,
        "from_block_ts": FROM_BLOCK_TS,
        "to_block": TO_BLOCK,
        "to_block_ts": TO_BLOCK_TS,
        "extracted_at": int(time.time()),
        "avg_share_price": avg_price,
        "pre_balances": serializable_pre,
        "events": serializable_events,
    }
    with open(data_path, "w") as f:
        json.dump(extraction, f)
    print(f"Wrote extraction data to {data_path}")


if __name__ == "__main__":
    main()
