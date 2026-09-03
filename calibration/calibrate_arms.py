#!/usr/bin/env python
"""SO-101 4-arm calibration wrapper (leader x2, follower x2).

Run via the lerobot repo's venv:
    uv run --project /home/youngchan/lerobot python calibration/calibrate_arms.py --all
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ARMS_JSON = Path(__file__).parent / "arms.json"
REPORT_JSON = Path(__file__).parent / "calibration_report.json"
VALID_TYPES = {"so101_leader", "so101_follower"}


def load_arms():
    with open(ARMS_JSON) as f:
        return json.load(f)


def self_test():
    arms = load_arms()
    checks = []

    ids = [a.get("id") for a in arms]
    ports = [a.get("port") for a in arms]

    checks.append(("all entries have id/type/port", all({"id", "type", "port"} <= a.keys() for a in arms)))
    checks.append(("all ids unique", len(ids) == len(set(ids))))
    checks.append(("all ports unique", len(ports) == len(set(ports))))
    checks.append(("all types valid", all(a.get("type") in VALID_TYPES for a in arms)))

    ok = True
    for name, passed in checks:
        print(f"{'PASS' if passed else 'FAIL'}: {name}")
        ok = ok and passed

    return 0 if ok else 1


def build_device(arm):
    """Build a connected-but-not-calibrated robot/teleoperator instance from an arms.json entry."""
    from lerobot.robots.config import RobotConfig
    from lerobot.robots.utils import make_robot_from_config
    from lerobot.teleoperators.config import TeleoperatorConfig
    from lerobot.teleoperators.utils import make_teleoperator_from_config

    arm_type = arm["type"]
    if arm_type == "so101_leader":
        config_cls = TeleoperatorConfig.get_choice_class(arm_type)
        config = config_cls(port=arm["port"], id=arm["id"])
        return make_teleoperator_from_config(config)
    elif arm_type == "so101_follower":
        config_cls = RobotConfig.get_choice_class(arm_type)
        config = config_cls(port=arm["port"], id=arm["id"])
        return make_robot_from_config(config)
    else:
        raise ValueError(f"Unknown arm type: {arm_type}")


def calibrate_one(arm):
    device = build_device(arm)
    device.connect(calibrate=False)
    try:
        device.calibrate()
    finally:
        device.disconnect()


def run_all(arms):
    failures = []
    for i, arm in enumerate(arms, 1):
        print(f"=== [{i}/{len(arms)}] {arm['id']} ({arm['type']}, {arm['port']}) ===")
        try:
            calibrate_one(arm)
        except Exception as e:
            print(f"ERROR calibrating {arm['id']}: {e}")
            failures.append(arm["id"])
    print()
    if failures:
        print(f"SUMMARY: {len(arms) - len(failures)}/{len(arms)} succeeded. Failed: {', '.join(failures)}")
        return 1
    print(f"SUMMARY: {len(arms)}/{len(arms)} succeeded.")
    return 0


def run_id(arms, arm_id):
    for arm in arms:
        if arm["id"] == arm_id:
            print(f"=== {arm['id']} ({arm['type']}, {arm['port']}) ===")
            calibrate_one(arm)
            return 0
    print(f"ERROR: no arm with id '{arm_id}' in arms.json")
    return 1


def run_verify(arms):
    results = []
    for arm in arms:
        device = build_device(arm)
        device.connect(calibrate=False)
        try:
            is_calibrated = device.is_calibrated
        finally:
            device.disconnect()
        results.append({"id": arm["id"], "type": arm["type"], "is_calibrated": is_calibrated})

    print(f"{'ID':<16} {'TYPE':<16} {'RESULT'}")
    for r in results:
        print(f"{r['id']:<16} {r['type']:<16} {'PASS' if r['is_calibrated'] else 'FAIL'}")

    report = {"timestamp": datetime.now(timezone.utc).isoformat(), "results": results}
    with open(REPORT_JSON, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nWrote {REPORT_JSON}")

    return 0 if all(r["is_calibrated"] for r in results) else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Calibrate all arms in arms.json, in order")
    group.add_argument("--id", metavar="ID", help="Calibrate only the matching arm")
    group.add_argument("--verify", action="store_true", help="Check calibration status of all arms")
    group.add_argument("--self-test", action="store_true", help="Validate arms.json (no hardware)")
    args = parser.parse_args()

    if args.self_test:
        sys.exit(self_test())

    arms = load_arms()
    if args.all:
        sys.exit(run_all(arms))
    elif args.id:
        sys.exit(run_id(arms, args.id))
    elif args.verify:
        sys.exit(run_verify(arms))


if __name__ == "__main__":
    main()
