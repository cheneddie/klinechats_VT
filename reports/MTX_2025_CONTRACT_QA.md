# MTX 2025 Contract QA

## Source
Validation was run against the user-supplied `MTX_2025.parquet` (39,416,621 physical rows) using an order-preserving native Parquet reader in the development environment.

The raw Parquet file is **not** committed to GitHub.

## Day-session contract result
Scope: MTX outright monthly contracts, regular day session 08:45–13:45.

- trading days observed: **236**
- day-session dates containing more than one monthly outright contract: **0**
- causal calendar-front selector vs actual day-session contract: **236 / 236 matched**
- mismatches: **0**
- contract switches: **12**

## Observed 2025 switches

| First day on new contract | From | To |
|---|---|---|
| 2025-01-16 | 202501 | 202502 |
| 2025-02-20 | 202502 | 202503 |
| 2025-03-20 | 202503 | 202504 |
| 2025-04-17 | 202504 | 202505 |
| 2025-05-22 | 202505 | 202506 |
| 2025-06-19 | 202506 | 202507 |
| 2025-07-17 | 202507 | 202508 |
| 2025-08-21 | 202508 | 202509 |
| 2025-09-18 | 202509 | 202510 |
| 2025-10-16 | 202510 | 202511 |
| 2025-11-20 | 202511 | 202512 |
| 2025-12-18 | 202512 | 202601 |

These switches are consistent with keeping the expiring monthly contract through its third-Wednesday expiry day and moving to the next month on the following trading date.

## Why this matters
The Decision Gym must never mix different monthly contracts into one Previous Value / Volume Profile / Auction state. Production `strict` mode therefore uses the calendar-front policy and **does not use completed-day volume rank** to choose the contract.

`dominant_volume` remains available only as an explicitly non-causal research diagnostic.

## Data-order boundary
This QA did not reorder source Tick rows. Physical file-row sequence remains the source of truth for same-second trades.
