-- RetailMind intelligence layer: identity, stock, memory.
-- Run once in Supabase SQL editor or via MCP apply_migration.

-- 1. Identity fix: persist owner's first name on the retailer row.
alter table retailers add column if not exists owner_name text;

-- 2. Stock — latest snapshot per (retailer, product). Upsert on each input.
create table if not exists stock_snapshots (
  retailer_id text not null references retailers(id) on delete cascade,
  product     text not null,
  units       numeric not null,
  set_at      timestamptz not null default now(),
  primary key (retailer_id, product)
);

-- 3. Conversation history — capped to ~last 16 per retailer at read time.
create table if not exists conversation_messages (
  id          bigserial primary key,
  retailer_id text not null references retailers(id) on delete cascade,
  role        text not null check (role in ('user', 'assistant')),
  content     text not null,
  created_at  timestamptz not null default now()
);
create index if not exists conv_msgs_retailer_recent
  on conversation_messages (retailer_id, created_at desc);

-- 4. Long-term facts — LLM writes via `remember(fact)`, prompt reads on every turn.
create table if not exists retailer_notes (
  id          bigserial primary key,
  retailer_id text not null references retailers(id) on delete cascade,
  fact        text not null,
  created_at  timestamptz not null default now()
);
create index if not exists retailer_notes_by_retailer
  on retailer_notes (retailer_id, created_at desc);
