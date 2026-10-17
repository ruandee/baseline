# TimescaleDB for voice-check time series

Baseline stores one wide row per 10-second voice check and queries daily medians and rolling baselines per resident. The database image changes from `pgvector/pgvector:0.8.2-pg17` to `timescale/timescaledb-ha:pg17`, and `voice_checks` becomes a hypertable partitioned on `ts` in 7-day chunks. `time_bucket` serves the overview series. Continuous aggregates are out of scope for now.

**Constraints that must hold:**

- `timescaledb-ha` has to include pgvector, because the existing retrieval path depends on it; if it does not, install it in the image. BL-03 confirms this.
- Row-level security must apply to hypertable chunks when queried as `pm_runtime`. BL-03 tests this on all three new tables. If it does not hold, drop the `create_hypertable` call, keep `voice_checks` as a plain table (`time_bucket` still works on plain tables), and amend this record.
- Primary key `(tenant_id, patient_id, id, ts)` includes the partition column, as hypertables require; composite foreign keys to `patients(tenant_id, id)` are kept.
- Migrations 001 and 002 are unchanged and must still pass from an empty database. The extension is created in 003 only.

**Why not plain Postgres:** it would work at demo scale. Timescale is chosen because the data is genuinely time series and the hackathon has a Tiger Data prize track; the fallback above keeps the decision cheap to reverse.

**Image pinning:** the current compose file pins images by digest. Pin the new image the same way once BL-03 selects the tag.

## Outcome (BL-03)

**Image:** `timescale/timescaledb-ha:pg17` pinned in `compose.yaml` by the multi-arch index digest `sha256:20534b8a…` (linux/amd64 and linux/arm64). It ships PostgreSQL 17.11, TimescaleDB 2.30.2 and pgvector 0.8.7 (was 0.8.2), so nothing needs installing. The data directory moved to `/home/postgres/pgdata/data`, so compose mounts the new named volume `pgdata_timescale` there. The old `pgdata` volume is left untouched; reload the synthetic fixtures after switching. Migrations 001 and 002 pass unchanged from an empty database, and the 80 existing tests pass on the new image.

**`voice_checks` is a plain table, not a hypertable.** The constraint above did not hold. Measured against the pinned image with a non-superuser, `NOBYPASSRLS` role:

- Queries through the hypertable are filtered correctly: each tenant saw only its own row, and a forged insert for another tenant was rejected.
- Chunk tables have no row security (`relrowsecurity = f`) and copy the hypertable's grants, so `SELECT` on `_timescaledb_internal._hyper_*_chunk` as that role returned **both tenants' rows**.
- Closing that by revoking `USAGE` on `_timescaledb_internal` also broke ordinary hypertable inserts and selects. A per-chunk revoke would not last: new chunks inherit the hypertable's grants.

So the fallback in the second constraint applies. `003_baseline` creates the extension and a plain `voice_checks` with the same columns and primary key, so converting later is one `create_hypertable(..., migrate_data => true)` call. `tests/integration/test_baseline_rls.py` fails if any new table becomes a hypertable; replace that guard with a chunk-access test when it is reopened.

**Open for the team:** with no hypertable, the image switch only buys `time_bucket`, which native `date_bin` (PostgreSQL 14+) also covers for fixed intervals. Keeping the image keeps the Timescale story and costs a heavier image (about 880 MB) and the volume change; reverting is one compose edit.
