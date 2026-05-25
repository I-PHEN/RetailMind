-- RetailMind initial schema
-- Run once in Supabase SQL editor: https://app.supabase.com → SQL Editor

create table if not exists retailers (
  id              text primary key,
  name            text not null,
  whatsapp        text not null unique,
  currency        text not null default 'USD',
  timezone        text not null default 'Africa/Lagos',
  digest_time     text not null default '08:00',
  spreadsheet_id  text,
  google_token    jsonb,
  status          text not null default 'onboarding'
    check (status in ('onboarding', 'active', 'paused')),
  created_at      timestamptz default now()
);

create table if not exists onboarding_state (
  whatsapp    text primary key,
  step        text not null
    check (step in ('awaiting_name', 'awaiting_oauth', 'done')),
  data        jsonb default '{}',
  updated_at  timestamptz default now()
);

-- auto-update updated_at on onboarding_state
create or replace function set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger onboarding_state_updated_at
  before update on onboarding_state
  for each row execute procedure set_updated_at();
