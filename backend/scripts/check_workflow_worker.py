"""Exit 0 only if latest worker heartbeat is successful and recent.

Run from backend/: python scripts/check_workflow_worker.py [--max-age 60]
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--health-file', type=Path, default=Path(os.environ.get(
        'WORKFLOW_HEALTH_FILE', '.runtime/workflow_worker.json')))
    parser.add_argument('--max-age', type=float, default=60)
    args = parser.parse_args()
    try:
        data = json.loads(args.health_file.read_text(encoding='utf-8'))
        updated = datetime.fromisoformat(data['updated_at'])
        age = (datetime.now(timezone.utc) - updated.astimezone(timezone.utc)).total_seconds()
        if data.get('success') and 0 <= age <= args.max_age:
            print(f'HEALTHY: workflow worker successful {age:.0f}s ago')
            return 0
        print(f'UNHEALTHY: last batch success={data.get("success")} age={age:.0f}s')
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f'UNHEALTHY: heartbeat missing/invalid: {exc}')
    return 1


if __name__ == '__main__':
    sys.exit(main())
