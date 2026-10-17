# TimescaleDB for voice-check time series

Baseline stores one wide row per 10-second voice check and queries daily medians and rolling baselines per resident. The database image changes from `pgvector/pgvector:0.8.2-pg17` to `timescale/timescaledb-ha:pg17`, and `voice_checks` becomes a hypertable partitioned on `ts` in 7-day chunks. `time_bucket` serves the overview series. Continuous aggregates are out of scope for now.

**Constraints that must hold:**

- `timescaledb-ha` has to include pgvector, because the existing retrieval path depends on it; if it does not, install it in the image. BL-03 confirms this.
- Row-level security must apply to hypertable chunks when queried as `pm_runtime`. BL-03 tests this on all three new tables. If it does not hold, drop the `create_hypertable` call, keep `voice_checks` as a plain table (`time_bucket` still works on plain tables), and amend this record.
- Primary key `(tenant_id, patient_id, id, ts)` includes the partition column, as hypertables require; composite foreign keys to `patients(tenant_id, id)` are kept.
- Migrations 001 and 002 are unchanged and must still pass from an empty database. The extension is created in 003 only.

**Why not plain Postgres:** it would work at demo scale. Timescale is chosen because the data is genuinely time series and the hackathon has a Tiger Data prize track; the fallback above keeps the decision cheap to reverse.

**Image pinning:** the current compose file pins images by digest. Pin the new image the same way once BL-03 selects the tag.
