"""One complete canonical A-028 payload shared by Harness boundary tests."""

from typing import Any


def vitals_payload() -> dict[str, Any]:
    return {
        "as_of": "2026-08-02T12:05:30Z",
        "window_minutes": 60,
        "spend": {
            "source_view": "v_spend_rate",
            "latest_minute": "2026-08-02T12:05:00Z",
            "lanes": [
                {
                    "dimension": "total",
                    "key": None,
                    "label": "All spend",
                    "points": [
                        {
                            "minute": "2026-08-02T12:05:00Z",
                            "cost_usd": "0.001200000000",
                            "receipt_lines": 3,
                            "unpriced_lines": 1,
                        }
                    ],
                },
                {
                    "dimension": "purpose",
                    "key": "building",
                    "label": "building",
                    "points": [
                        {
                            "minute": "2026-08-02T12:05:00Z",
                            "cost_usd": "0.001200000000",
                            "receipt_lines": 3,
                            "unpriced_lines": 1,
                        }
                    ],
                },
                {
                    "dimension": "model",
                    "key": "vendor/model",
                    "label": "vendor/model",
                    "points": [
                        {
                            "minute": "2026-08-02T12:05:00Z",
                            "cost_usd": "0.001200000000",
                            "receipt_lines": 3,
                            "unpriced_lines": 1,
                        }
                    ],
                },
            ],
        },
        "lifecycle_rates": [
            {
                "metric": "created",
                "status": "measured",
                "per_hour": 2,
                "source": "memory_unit.created_at",
            },
            *[
                {"metric": metric, "status": "not_recorded", "per_hour": None, "source": None}
                for metric in (
                    "reinforced",
                    "superseded",
                    "merged",
                    "quarantined",
                    "tombstoned",
                    "add_backs",
                )
            ],
        ],
        "palace_counts": [
            {
                "metric": "active_units",
                "status": "measured",
                "count": 11,
                "source": "memory_unit.status",
            },
            {
                "metric": "pinned_units",
                "status": "measured",
                "count": 2,
                "source": "memory_unit.status+pin",
            },
            {
                "metric": "candidates_pending",
                "status": "measured",
                "count": 3,
                "source": "memory_unit.status",
            },
            {
                "metric": "edges",
                "status": "measured",
                "count": 4,
                "source": "memory_edge",
            },
            {"metric": "staged_units", "status": "not_recorded", "count": None, "source": None},
            {
                "metric": "queue_depth",
                "status": "measured",
                "count": 3,
                "source": "approval_queue_item.state",
            },
        ],
    }


__all__ = ["vitals_payload"]
