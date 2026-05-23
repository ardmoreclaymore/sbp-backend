-- SBP clean v7 Supabase schema
-- Run in Supabase SQL Editor after deleting old SBP tables.

create table if not exists public.items (
  id text primary key,
  name text not null,
  source text not null,
  market_type text,
  source_tag text,
  category text,
  tier text,
  tags jsonb,
  current_price numeric,
  fair_price numeric,
  median_price numeric,
  avg_price numeric,
  second_lowest_price numeric,
  buy_price numeric,
  sell_price numeric,
  spread_pct numeric,
  buy_volume numeric,
  sell_volume numeric,
  buy_moving_week numeric,
  sell_moving_week numeric,
  buy_orders numeric,
  sell_orders numeric,
  volume numeric,
  volume_24h numeric,
  listed_count integer,
  sold_count_24h integer,
  price_change_5m_pct numeric,
  history_points integer default 0,
  example_names jsonb,
  raw_data jsonb,
  updated_at timestamptz
);

create table if not exists public.price_snapshots (
  id bigserial primary key,
  item_id text not null,
  price numeric,
  current_price numeric,
  fair_price numeric,
  median_price numeric,
  avg_price numeric,
  second_lowest_price numeric,
  buy_price numeric,
  sell_price numeric,
  buy_volume numeric,
  sell_volume numeric,
  buy_moving_week numeric,
  sell_moving_week numeric,
  buy_orders numeric,
  sell_orders numeric,
  volume numeric,
  volume_24h numeric,
  listed_count integer,
  sold_count_24h integer,
  spread_pct numeric,
  manipulation_score numeric,
  source text,
  market_type text,
  raw_data jsonb,
  created_at timestamptz default now()
);

create table if not exists public.predictions (
  item_id text primary key,
  name text not null,
  source text,
  current_price numeric,
  forecast_change_pct numeric,
  rank_score numeric,
  predicted_direction text,
  confidence numeric,
  certainty numeric,
  expected_price numeric,
  expected_low numeric,
  expected_high numeric,
  timeframe text,
  driver text,
  reason text,
  risk text,
  risk_factors text,
  risk_level text,
  manipulation_score numeric,
  manipulation_flags jsonb,
  top_outcomes jsonb,
  similar_cases text,
  tags jsonb,
  demand text,
  supply text,
  volume numeric,
  volume_24h numeric,
  buy_price numeric,
  sell_price numeric,
  spread_pct numeric,
  buy_volume numeric,
  sell_volume numeric,
  buy_moving_week numeric,
  sell_moving_week numeric,
  buy_orders numeric,
  sell_orders numeric,
  listed_count integer,
  sold_count_24h integer,
  market_type text,
  category text,
  raw_data jsonb,
  updated_at timestamptz
);

create table if not exists public.market_context (
  id integer primary key,
  project_name text,
  current_mayor text,
  current_perks jsonb,
  election_candidates jsonb,
  current_meta text,
  meta_methods jsonb,
  tracked_items_total integer,
  tracked_bazaar_items integer,
  tracked_auction_items integer,
  ai_factor_1 text,
  ai_factor_2 text,
  source_status jsonb,
  updated_at timestamptz
);

create table if not exists public.source_status (
  id text primary key,
  name text,
  url text,
  status text,
  message text,
  updated_at timestamptz
);

create table if not exists public.prediction_backtests (
  id bigserial primary key,
  item_id text not null,
  prediction_created_at timestamptz,
  target_time timestamptz,
  predicted_direction text,
  predicted_price numeric,
  expected_low numeric,
  expected_high numeric,
  actual_price numeric,
  direction_correct boolean,
  range_hit boolean,
  error_pct numeric,
  notes text,
  created_at timestamptz default now()
);

create table if not exists public.prediction_factors (
  id bigserial primary key,
  factor_key text unique,
  sheet_name text,
  row_number integer,
  variable_name text,
  category text,
  item_group text,
  market_source text,
  direction text,
  estimated_impact_min_pct numeric,
  estimated_impact_max_pct numeric,
  reliability_score numeric,
  confidence_notes text,
  source_url text,
  raw_data jsonb,
  enabled boolean default true,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index if not exists idx_items_source_price on public.items(source, current_price desc);
create index if not exists idx_items_name on public.items(name);
create index if not exists idx_snapshots_item_time on public.price_snapshots(item_id, created_at desc);
create index if not exists idx_predictions_rank on public.predictions(rank_score desc);
create index if not exists idx_predictions_manipulation on public.predictions(manipulation_score);
create index if not exists idx_prediction_factors_enabled on public.prediction_factors(enabled);

grant usage on schema public to anon, authenticated, service_role;
grant select on public.items to anon, authenticated, service_role;
grant select on public.price_snapshots to anon, authenticated, service_role;
grant select on public.predictions to anon, authenticated, service_role;
grant select on public.market_context to anon, authenticated, service_role;
grant select on public.source_status to anon, authenticated, service_role;
grant all privileges on public.items to service_role;
grant all privileges on public.price_snapshots to service_role;
grant all privileges on public.predictions to service_role;
grant all privileges on public.market_context to service_role;
grant all privileges on public.source_status to service_role;
grant all privileges on public.prediction_backtests to service_role;
grant all privileges on public.prediction_factors to service_role;
grant usage, select, update on all sequences in schema public to service_role;

alter table public.items enable row level security;
alter table public.price_snapshots enable row level security;
alter table public.predictions enable row level security;
alter table public.market_context enable row level security;
alter table public.source_status enable row level security;
alter table public.prediction_backtests enable row level security;
alter table public.prediction_factors enable row level security;

drop policy if exists "Public read items" on public.items;
create policy "Public read items" on public.items for select to anon using (true);
drop policy if exists "Public read price snapshots" on public.price_snapshots;
create policy "Public read price snapshots" on public.price_snapshots for select to anon using (true);
drop policy if exists "Public read predictions" on public.predictions;
create policy "Public read predictions" on public.predictions for select to anon using (true);
drop policy if exists "Public read market context" on public.market_context;
create policy "Public read market context" on public.market_context for select to anon using (true);
drop policy if exists "Public read source status" on public.source_status;
create policy "Public read source status" on public.source_status for select to anon using (true);
drop policy if exists "Service role manage factors" on public.prediction_factors;
create policy "Service role manage factors" on public.prediction_factors for all to service_role using (true) with check (true);

notify pgrst, 'reload schema';
