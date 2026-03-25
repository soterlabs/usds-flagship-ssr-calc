"""Verify that all addresses in reward JSON files are EIP-55 checksummed."""

import glob
import json
import os

from Crypto.Hash import keccak


def is_checksum_address(address):
    """Check if address is valid EIP-55 checksummed."""
    if not address.startswith("0x") or len(address) != 42:
        return False
    addr = address[2:]
    k = keccak.new(digest_bits=256, data=addr.lower().encode("ascii"))
    hash_hex = k.hexdigest()
    for i, c in enumerate(addr):
        if c in "0123456789":
            continue
        expected_upper = int(hash_hex[i], 16) >= 8
        if expected_upper and not c.isupper():
            return False
        if not expected_upper and not c.islower():
            return False
    return True


from calculate_rewards import to_checksum_address


# Official EIP-55 test vectors from https://eips.ethereum.org/EIPS/eip-55
EIP55_VECTORS = [
    # all caps
    "0x52908400098527886E0F7030069857D2E4169EE7",
    "0x8617E340B3D01FA5F11F306F4090FD50E238070D",
    # all lower
    "0xde709f2102306220921060314715629080e2fb77",
    "0x27b1fdb04752bbc536007a920d24acb045561c26",
    # normal
    "0x5aAeb6053F3E94C9b9A09f33669435E7Ef1BeAed",
    "0xfB6916095ca1df60bB79Ce92cE3Ea74c37c5d359",
    "0xdbF03B407c01E7cD3CBea99509d93f8DDDC8C6FB",
    "0xD1220A0cf47c7B9Be7A2E6BA89F429762e7b9aDb",
]


def test_eip55_vectors():
    """Verify to_checksum_address matches official EIP-55 test vectors."""
    for expected in EIP55_VECTORS:
        result = to_checksum_address(expected.lower())
        assert result == expected, (
            f"EIP-55 mismatch for {expected.lower()}: "
            f"got {result}, expected {expected}"
        )


def test_is_checksum_address_rejects_bad_checksums():
    """Verify is_checksum_address rejects incorrectly cased addresses."""
    for addr in EIP55_VECTORS:
        # Flip the case of the first alpha character to break the checksum
        broken = list(addr)
        for i in range(2, len(broken)):
            if broken[i].isalpha():
                broken[i] = broken[i].swapcase()
                break
        broken = "".join(broken)
        assert not is_checksum_address(broken), (
            f"Should have rejected {broken}"
        )


REPO_DIR = os.path.dirname(os.path.abspath(__file__))


def find_reward_files():
    return sorted(glob.glob(os.path.join(REPO_DIR, "rewards_*.json")))


def test_reward_files_exist():
    files = find_reward_files()
    assert files, "No rewards_*.json files found"


def test_all_addresses_are_checksummed():
    for path in find_reward_files():
        fname = os.path.basename(path)
        with open(path) as f:
            data = json.load(f)

        # Check rewardToken
        rt = data.get("rewardToken", "")
        assert is_checksum_address(rt), (
            f"{fname}: rewardToken {rt} is not properly checksummed"
        )

        # Check every depositor address key
        bad = []
        for addr in data.get("rewards", {}):
            if not is_checksum_address(addr):
                bad.append(addr)

        assert not bad, (
            f"{fname}: {len(bad)} addresses not properly checksummed. "
            f"First 5: {bad[:5]}"
        )


if __name__ == "__main__":
    import sys
    try:
        test_reward_files_exist()
        test_all_addresses_are_checksummed()
        print("All checksum tests passed.")
    except AssertionError as e:
        print(f"FAIL: {e}", file=sys.stderr)
        sys.exit(1)
