County-level annual business registrations and deregistrations for the socio-demographics staging area.

## Verified source and mapping

- **Provider:** Regionaldatenbank Deutschland (GENESIS Regional), table `52311-01-04-4`.
- **Table title:** *Gewerbeanmeldungen, -abmeldungen - Jahressumme - regionale Tiefe: Kreise und krfr. Städte*.
- **Official table page:** <https://www.regionalstatistik.de/datenbank/online/statistic/52311/table/52311-01-04-4>
- **Read API:** `GET https://www.regionalstatistik.de/gngServer/api/rest/tables/52311-01-04-4/structure` and `/data`.
- **Regional key:** the table's `KREISE` dimension. The loader keeps only five-digit numeric county/county-independent-city keys (official county level) and excludes the additional eight-digit subcounty detail present for some cities and states. Keys remain strings to preserve leading zeroes.
- **Observation period:** annual values, as supplied by the table; current API response covers 1998–2025. The loader does not fabricate years missing from the source.
- **Measures:** `GEW011$QMU` → registrations; `GEW013$QMU` → deregistrations; `QMU` is verified as `Anzahl` (count). Values are stored as integers; source null/missing markers remain SQL `NULL`.
- **Target key:** `(source_table_code, county_key, observation_year)`. Repeated identical loads do not change rows; changed source observations update the existing key.
- **CRS:** this table is tabular and contains no geometry. No county geometry is fabricated or joined from another source; EPSG:25832 and `shapely.make_valid()` are therefore not applicable to this input. The output preserves the official regional key instead.

The federal Destatis GENESIS table group `52311` is not the county source: its table `52311-0150` is by federal state. This implementation uses the verified Regionaldatenbank table above, whose metadata identifies `KREISE`. The Regionaldatenbank data endpoint returns the full table cube in one response; no paging token is exposed for this table. Transient throttling and server errors are retried with bounded backoff.

The source cube also includes historical county keys across its time series. The loader preserves every five-digit key and its supplied value for the requested year; it does not infer a key's validity period from zero counts. As a result, a selected year can include historical keys with source values of zero, and `processed_count` is the number of source-key/year rows, not a count of currently active counties.

## Important measure limitation

The official source calls the second measure **Gewerbeabmeldungen** (business deregistrations), not liquidations. Its definition includes full business closures as well as relocations to another reporting district and other events such as sale, succession, or legal-form changes. Do not interpret the count as a number of insolvencies, liquidations, or permanently closed businesses. Registrations also include notifications beyond new business formation. These counts are contextual regional indicators, not property-level demand or valuation inputs.

## Schema mapping

| GENESIS source | Normalized field | Type / unit |
|---|---|---|
| `KREISE` key, only 5-digit values | `county_key` | string, 5 digits |
| `variableValues[KREISE].label.de` | `county_name` | text |
| `JAHR` | `observation_year` | integer year |
| `GEW011$QMU` | `registrations` | nullable integer, `Anzahl` |
| `GEW013$QMU` | `deregistrations` | nullable integer, `Anzahl` |
| table code | `source_table_code` | `52311-01-04-4` |
| table metadata `lastChange` | `source_updated_at` | nullable timestamp |
| ETL retrieval time | `source_retrieved_at` | UTC timestamp |
| official table page | `source_url` | URL |

The file [`sql/schema.sql`](./sql/schema.sql) defines a **candidate-owned provisional** shape for `iris_staging.socio_demographics_staging`. No Tariq-approved/shared target DDL was provided or verified. Confirm the shared target contract before using that DDL against a shared database.

## Run locally

Requirements: Python 3.11+ and outbound HTTPS access to Regionaldatenbank for a live fetch. A database is only required when testing persistence. The commands below are run from the repository root.

### Python tests and smoke run

**Windows PowerShell:**

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --requirement requirements.txt
python -m pytest -q
```

**macOS / Linux:**

```sh
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --requirement requirements.txt
python -m pytest -q
```

Offline smoke run using the clearly synthetic test fixture:

**Windows PowerShell:**

```powershell
python -m task_cre_50 --input-json tests\fixtures\genesis_regional_sample.json --start-year 2024 --end-year 2024
```

**macOS / Linux:**

```sh
python -m task_cre_50 --input-json tests/fixtures/genesis_regional_sample.json --start-year 2024 --end-year 2024
```

Live source validation without database writes:

```text
python -m task_cre_50 --start-year 2024 --end-year 2025
```

The Regionaldatenbank currently returns the public table through unauthenticated GET requests in the tested environment. Its web-service information also announces a free registration requirement; if the service requires credentials for your environment, set both variables before running:

```powershell
$env:GENESIS_USERNAME = "<your registered username>"
$env:GENESIS_PASSWORD = "<your password>"
```

For staging persistence, first confirm the target DDL. Docker Engine/Desktop and Compose V2 are required. On Windows, install and start Docker Desktop with the WSL2 backend; on macOS/Linux, install and start Docker Engine and the Compose V2 plugin using the official Docker instructions for your OS. Confirm `docker --version` and `docker compose version` work before continuing.

The Compose setup binds PostGIS to `127.0.0.1:55432` only and initializes the provisional schema in a named local volume. From the repository root, create a local `.env` file and replace the example password with a unique local password. `.env` is ignored by Git and excluded from Docker build contexts:

```powershell
Copy-Item .env.example .env
notepad .env
docker compose up -d
docker compose ps
```

On macOS/Linux, create and edit the file with:

```sh
cp .env.example .env
${EDITOR:-vi} .env
docker compose up -d
docker compose ps
```

The Compose ETL profile builds and runs the loader inside the Compose network, where it can reach the database by service name. It avoids requiring the host Python environment to connect to Docker's private network:

```text
docker compose --profile etl run --build --rm task-cre-50 --start-year 2024 --end-year 2025 --load-db
```

The CLI does not write unless `--load-db` is explicitly supplied. Database loading validates PostgreSQL 16, PostGIS 3.4 availability, and the required columns before writing. Candidate data writes are restricted to `iris_staging`; no production target is available in the code. Stop the local test database with `docker compose down`. The named volume is preserved. `docker compose down -v` deletes the local test database volume.

### Optional standalone Docker image

From the repository root, build and run the fixture smoke test:

```text
docker build -t task-cre-50:local .
docker run --rm task-cre-50:local --input-json tests/fixtures/genesis_regional_sample.json --start-year 2024 --end-year 2024
```

Omit `--input-json` for a live fetch. To write to a database from a standalone container, pass `DB_URI` at runtime and ensure the container can reach that database; never bake credentials into the image. The image entrypoint is `python -m task_cre_50`.

## Output and idempotency evidence

The fixture smoke run returns this summary (the fixture contains two county rows for 2024 and one explicit missing measure):

```json
{"database_loaded": false, "failed_count": 0, "inserted_count": 0, "missing_value_rows": 1, "processed_count": 2, "source_table_code": "52311-01-04-4", "updated_count": 0}
```

The storage statement uses `ON CONFLICT (source_table_code, county_key, observation_year)`. It updates only when source values or source metadata differ, so a repeated identical input results in neither duplicate keys nor timestamp-only updates. Its returned insert/update counts reflect rows actually inserted or changed.

Example staging verification queries:

```sql
SELECT observation_year, COUNT(*) AS county_rows,
       COUNT(*) FILTER (WHERE registrations IS NULL) AS missing_registration_counts,
       COUNT(*) FILTER (WHERE deregistrations IS NULL) AS missing_deregistration_counts
FROM iris_staging.socio_demographics_staging
WHERE source_table_code = '52311-01-04-4'
GROUP BY observation_year
ORDER BY observation_year;

SELECT source_table_code, county_key, observation_year, COUNT(*)
FROM iris_staging.socio_demographics_staging
GROUP BY source_table_code, county_key, observation_year
HAVING COUNT(*) > 1;
```

Automated tests cover API URL, language, and timeout parameters; HTTP, JSON, and invalid-response handling; credential and timeout validation; table and measure validation; county-level key filtering; leading-zero preservation; year filtering and invalid ranges; timezone validation; malformed and duplicate cubes; missing-value handling; integer validation; dry-run counts; DB URI enforcement; staging-only upsert SQL; and duplicate stable keys within a write batch. Run them with `python -m pytest -q`.

Local Docker integration was exercised with PostgreSQL 16.4 and PostGIS 3.4.3. The first live 2024 load inserted 475 rows; repeating it inserted 0 and updated 0. SQL verification found 475 observations across 475 regional keys and 0 duplicate stable keys. These are local candidate staging results only; no shared or production database was accessed.

## Logging and failures

HTTP requests use explicit timeouts and retry transient `429`/`5xx` responses with backoff. Invalid JSON, unexpected table/units/dimensions, duplicate or incomplete cells, invalid counts, missing DB configuration, database version mismatch, and target schema mismatch fail with a non-zero exit code and an error log. A database batch is one transaction; failed loads are rolled back and logged as failed rows.

## Limitations and provenance

- The source table is annual and its rows are statistical geography totals, not individual business establishments.
- The table metadata describes an NRW reporting issue: 2022 data were underreported in some municipalities and 2023 includes delivered late reports, resulting in overreporting. Interpret those years cautiously.
- County names and boundaries can change over historical periods. This load preserves the source key and year but does not apply an external historical boundary crosswalk.
- The source's full regional cube includes historical keys and returns zero-valued cells for some obsolete keys in later years (for example, `03156` has zero registrations and deregistrations for 2024). The source response does not provide a per-key validity interval in the table structure. Those zeroes are preserved exactly; downstream users should not treat each zero-valued key/year as proof of an active county with no business activity.
- No boundary polygons, CRS, or geometries are provided by this table; no spatial overlay or geometry repair is attempted.
- Data source attribution: **© Statistische Ämter des Bundes und der Länder, Deutschland, 2026. Datenlizenz Deutschland – Namensnennung – Version 2.0 (DL-DE BY 2.0)**. See <https://www.govdata.de/dl-de/by-2-0>. The table metadata supplies the applicable attribution/license; verify current terms and attribution when republishing.
- Live GENESIS access and the isolated local PostGIS integration were verified during implementation. No shared database, Tariq-approved DDL, coordinator approval status, or external credentials were available or verified. This is a candidate implementation, not evidence of authorized submission or a production load.
- The illustrative master playbook and approved target DDL were not present in the checked-out workspace, so the candidate DDL and adapter were built from the task contract and official table metadata.
