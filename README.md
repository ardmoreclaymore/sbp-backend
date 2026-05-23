# SBP Backend

Backend/API and collector for SkyBlock Price Predictor.

## Render Web Service

Start command:

```bash
uvicorn main:app --host 0.0.0.0 --port $PORT
```

## Render Cron Job

Schedule:

```cron
*/5 * * * *
```

Command:

```bash
python collector.py
```

## Required environment variables

```env
SUPABASE_URL=your_supabase_url
SUPABASE_SERVICE_KEY=your_service_role_key
```

Optional:

```env
MINIMUM_PRICE=0
AH_MAX_PAGES=all
SNAPSHOT_KEEP_DAYS=14
```

Do not put service role keys in Bluehost or frontend JavaScript.

## Supabase

Run `supabase_schema.sql` in Supabase SQL Editor after deleting old SBP tables.
