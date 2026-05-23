-- SBP v6 schema migration
-- Run this in Supabase SQL editor before deploying the new collector.

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
  volume_24h numeric,
  listed_count integer,
  sold_count_24h integer,
  price_change_5m_pct numeric,
  history_points integer default 0,
  example_names jsonb,
  updated_at timestamptz
);

alter table public.items add column if not exists market_type text;
alter table public.items add column if not exists source_tag text;
alter table public.items add column if not exists category text;
alter table public.items add column if not exists tier text;
alter table public.items add column if not exists tags jsonb;
alter table public.items add column if not exists fair_price numeric;
alter table public.items add column if not exists median_price numeric;
alter table public.items add column if not exists avg_price numeric;
alter table public.items add column if not exists second_lowest_price numeric;
alter table public.items add column if not exists spread_pct numeric;
alter table public.items add column if not exists buy_orders numeric;
alter table public.items add column if not exists sell_orders numeric;
alter table public.items add column if not exists volume_24h numeric;
alter table public.items add column if not exists listed_count integer;
alter table public.items add column if not exists sold_count_24h integer;
alter table public.items add column if not exists price_change_5m_pct numeric;
alter table public.items add column if not exists history_points integer default 0;
alter table public.items add column if not exists example_names jsonb;

create table if not exists public.price_snapshots (
  id bigserial primary key,
  item_id text not null,
  price numeric,
  buy_price numeric,
  sell_price numeric,
  volume numeric,
  listed_count integer,
  spread_pct numeric,
  manipulation_score numeric,
  source text,
  created_at timestamptz default now()
);

alter table public.price_snapshots add column if not exists volume numeric;
alter table public.price_snapshots add column if not exists listed_count integer;
alter table public.price_snapshots add column if not exists spread_pct numeric;
alter table public.price_snapshots add column if not exists manipulation_score numeric;
alter table public.price_snapshots add column if not exists source text;

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
  manipulation_score numeric,
  manipulation_flags jsonb,
  top_outcomes jsonb,
  similar_cases text,
  tags jsonb,
  updated_at timestamptz
);

alter table public.predictions add column if not exists source text;
alter table public.predictions add column if not exists rank_score numeric;
alter table public.predictions add column if not exists predicted_direction text;
alter table public.predictions add column if not exists certainty numeric;
alter table public.predictions add column if not exists expected_price numeric;
alter table public.predictions add column if not exists expected_low numeric;
alter table public.predictions add column if not exists expected_high numeric;
alter table public.predictions add column if not exists timeframe text;
alter table public.predictions add column if not exists risk_factors text;
alter table public.predictions add column if not exists manipulation_score numeric;
alter table public.predictions add column if not exists manipulation_flags jsonb;
alter table public.predictions add column if not exists top_outcomes jsonb;
alter table public.predictions add column if not exists similar_cases text;
alter table public.predictions add column if not exists tags jsonb;

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

alter table public.market_context add column if not exists project_name text;
alter table public.market_context add column if not exists current_perks jsonb;
alter table public.market_context add column if not exists election_candidates jsonb;
alter table public.market_context add column if not exists meta_methods jsonb;
alter table public.market_context add column if not exists tracked_items_total integer;
alter table public.market_context add column if not exists tracked_bazaar_items integer;
alter table public.market_context add column if not exists tracked_auction_items integer;
alter table public.market_context add column if not exists source_status jsonb;

create table if not exists public.source_status (
  id text primary key,
  name text,
  url text,
  status text,
  message text,
  updated_at timestamptz
);

-- Optional table for later actual backtesting. The predictor can be improved to read these hit rates.
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

create index if not exists idx_items_source_price on public.items(source, current_price desc);
create index if not exists idx_items_name_trgm_like on public.items(name);
create index if not exists idx_snapshots_item_time on public.price_snapshots(item_id, created_at desc);
create index if not exists idx_predictions_rank on public.predictions(rank_score desc);
create index if not exists idx_predictions_manipulation on public.predictions(manipulation_score);
