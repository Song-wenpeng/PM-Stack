-- ReviewCollector cloud schema
-- Run this once in Supabase SQL Editor, then create users in Authentication.

create extension if not exists pgcrypto;
create schema if not exists private;

create table if not exists public.workspaces (
    id uuid primary key default gen_random_uuid(),
    owner_user_id uuid not null references auth.users(id) on delete cascade,
    name text not null default 'My Review Workspace',
    created_at timestamptz not null default now()
);

create table if not exists public.workspace_members (
    workspace_id uuid not null references public.workspaces(id) on delete cascade,
    user_id uuid not null references auth.users(id) on delete cascade,
    role text not null default 'owner' check (role in ('owner', 'editor', 'viewer')),
    created_at timestamptz not null default now(),
    primary key (workspace_id, user_id)
);

create table if not exists public.products (
    workspace_id uuid not null references public.workspaces(id) on delete cascade,
    marketplace text not null,
    asin text not null,
    parent_asin text not null default '',
    title text not null default '',
    note text not null default '',
    added_at timestamptz not null default now(),
    last_scraped_at timestamptz not null default now(),
    primary key (workspace_id, marketplace, asin)
);

create table if not exists public.reviews (
    workspace_id uuid not null references public.workspaces(id) on delete cascade,
    marketplace text not null,
    review_id text not null,
    rating numeric(2,1) check (rating is null or rating between 1 and 5),
    title text not null default '',
    content text not null default '',
    reviewer_name text not null default '',
    review_date date,
    review_date_raw text not null default '',
    verified_purchase boolean not null default false,
    helpful_votes integer not null default 0 check (helpful_votes >= 0),
    review_url text not null default '',
    image_urls jsonb not null default '[]'::jsonb,
    language text,
    raw_payload jsonb not null default '{}'::jsonb,
    first_seen_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    search_vector tsvector generated always as (
        to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(content, ''))
    ) stored,
    primary key (workspace_id, marketplace, review_id)
);

create index if not exists reviews_search_idx
    on public.reviews using gin(search_vector);
create index if not exists reviews_date_idx
    on public.reviews(workspace_id, marketplace, review_date desc);

create table if not exists public.product_reviews (
    workspace_id uuid not null,
    marketplace text not null,
    asin text not null,
    review_id text not null,
    star_filter text not null default '',
    page_number integer,
    first_seen_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    primary key (workspace_id, marketplace, asin, review_id),
    foreign key (workspace_id, marketplace, asin)
        references public.products(workspace_id, marketplace, asin) on delete cascade,
    foreign key (workspace_id, marketplace, review_id)
        references public.reviews(workspace_id, marketplace, review_id) on delete cascade
);

create index if not exists product_reviews_review_idx
    on public.product_reviews(workspace_id, marketplace, review_id);

create table if not exists public.collection_runs (
    id uuid primary key default gen_random_uuid(),
    workspace_id uuid not null references public.workspaces(id) on delete cascade,
    asin text not null,
    marketplace text not null,
    started_at timestamptz not null,
    finished_at timestamptz not null,
    new_reviews integer not null default 0,
    duplicate_reviews integer not null default 0,
    status text not null check (status in ('ok', 'partial', 'failed')),
    error text not null default ''
);

create table if not exists public.ingest_receipts (
    workspace_id uuid not null references public.workspaces(id) on delete cascade,
    idempotency_key text not null,
    received_at timestamptz not null default now(),
    primary key (workspace_id, idempotency_key)
);

create table if not exists public.review_analysis (
    id uuid primary key default gen_random_uuid(),
    workspace_id uuid not null,
    marketplace text not null,
    review_id text not null,
    analysis_type text not null,
    model text not null,
    prompt_version text not null,
    result jsonb not null,
    created_at timestamptz not null default now(),
    unique (workspace_id, marketplace, review_id, analysis_type, model, prompt_version),
    foreign key (workspace_id, marketplace, review_id)
        references public.reviews(workspace_id, marketplace, review_id) on delete cascade
);

create or replace function private.user_workspace_ids()
returns setof uuid
language sql
stable
security definer
set search_path = ''
as $$
    select wm.workspace_id
    from public.workspace_members wm
    where wm.user_id = (select auth.uid())
$$;

create or replace function private.writable_workspace_ids()
returns setof uuid
language sql
stable
security definer
set search_path = ''
as $$
    select wm.workspace_id
    from public.workspace_members wm
    where wm.user_id = (select auth.uid()) and wm.role in ('owner', 'editor')
$$;

create or replace function private.owned_workspace_ids()
returns setof uuid
language sql
stable
security definer
set search_path = ''
as $$
    select wm.workspace_id
    from public.workspace_members wm
    where wm.user_id = (select auth.uid()) and wm.role = 'owner'
$$;

revoke all on function private.user_workspace_ids() from public;
revoke all on function private.writable_workspace_ids() from public;
revoke all on function private.owned_workspace_ids() from public;
grant usage on schema private to authenticated;
grant execute on function private.user_workspace_ids() to authenticated;
grant execute on function private.writable_workspace_ids() to authenticated;
grant execute on function private.owned_workspace_ids() to authenticated;

alter table public.workspaces enable row level security;
alter table public.workspace_members enable row level security;
alter table public.products enable row level security;
alter table public.reviews enable row level security;
alter table public.product_reviews enable row level security;
alter table public.collection_runs enable row level security;
alter table public.ingest_receipts enable row level security;
alter table public.review_analysis enable row level security;

drop policy if exists workspaces_member_access on public.workspaces;
drop policy if exists workspaces_member_read on public.workspaces;
drop policy if exists workspaces_owner_manage on public.workspaces;
create policy workspaces_member_read on public.workspaces
    for select to authenticated
    using (id in (select private.user_workspace_ids()));
create policy workspaces_owner_manage on public.workspaces
    for all to authenticated
    using (id in (select private.owned_workspace_ids()))
    with check (id in (select private.owned_workspace_ids()));

drop policy if exists workspace_members_member_access on public.workspace_members;
drop policy if exists workspace_members_member_read on public.workspace_members;
drop policy if exists workspace_members_owner_manage on public.workspace_members;
create policy workspace_members_member_read on public.workspace_members
    for select to authenticated
    using (workspace_id in (select private.user_workspace_ids()));
create policy workspace_members_owner_manage on public.workspace_members
    for all to authenticated
    using (workspace_id in (select private.owned_workspace_ids()))
    with check (workspace_id in (select private.owned_workspace_ids()));

drop policy if exists products_member_access on public.products;
drop policy if exists products_member_read on public.products;
drop policy if exists products_writer_manage on public.products;
create policy products_member_read on public.products
    for select to authenticated
    using (workspace_id in (select private.user_workspace_ids()));
create policy products_writer_manage on public.products
    for all to authenticated
    using (workspace_id in (select private.writable_workspace_ids()))
    with check (workspace_id in (select private.writable_workspace_ids()));

drop policy if exists reviews_member_access on public.reviews;
drop policy if exists reviews_member_read on public.reviews;
drop policy if exists reviews_writer_manage on public.reviews;
create policy reviews_member_read on public.reviews
    for select to authenticated
    using (workspace_id in (select private.user_workspace_ids()));
create policy reviews_writer_manage on public.reviews
    for all to authenticated
    using (workspace_id in (select private.writable_workspace_ids()))
    with check (workspace_id in (select private.writable_workspace_ids()));

drop policy if exists product_reviews_member_access on public.product_reviews;
drop policy if exists product_reviews_member_read on public.product_reviews;
drop policy if exists product_reviews_writer_manage on public.product_reviews;
create policy product_reviews_member_read on public.product_reviews
    for select to authenticated
    using (workspace_id in (select private.user_workspace_ids()));
create policy product_reviews_writer_manage on public.product_reviews
    for all to authenticated
    using (workspace_id in (select private.writable_workspace_ids()))
    with check (workspace_id in (select private.writable_workspace_ids()));

drop policy if exists collection_runs_member_access on public.collection_runs;
drop policy if exists collection_runs_member_read on public.collection_runs;
drop policy if exists collection_runs_writer_manage on public.collection_runs;
create policy collection_runs_member_read on public.collection_runs
    for select to authenticated
    using (workspace_id in (select private.user_workspace_ids()));
create policy collection_runs_writer_manage on public.collection_runs
    for all to authenticated
    using (workspace_id in (select private.writable_workspace_ids()))
    with check (workspace_id in (select private.writable_workspace_ids()));

drop policy if exists ingest_receipts_member_access on public.ingest_receipts;
drop policy if exists ingest_receipts_member_read on public.ingest_receipts;
drop policy if exists ingest_receipts_writer_manage on public.ingest_receipts;
create policy ingest_receipts_member_read on public.ingest_receipts
    for select to authenticated
    using (workspace_id in (select private.user_workspace_ids()));
create policy ingest_receipts_writer_manage on public.ingest_receipts
    for all to authenticated
    using (workspace_id in (select private.writable_workspace_ids()))
    with check (workspace_id in (select private.writable_workspace_ids()));

drop policy if exists review_analysis_member_access on public.review_analysis;
drop policy if exists review_analysis_member_read on public.review_analysis;
drop policy if exists review_analysis_writer_manage on public.review_analysis;
create policy review_analysis_member_read on public.review_analysis
    for select to authenticated
    using (workspace_id in (select private.user_workspace_ids()));
create policy review_analysis_writer_manage on public.review_analysis
    for all to authenticated
    using (workspace_id in (select private.writable_workspace_ids()))
    with check (workspace_id in (select private.writable_workspace_ids()));

-- This narrowly scoped definer function creates only the caller's own workspace.
create or replace function public.ensure_personal_workspace()
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_user_id uuid := auth.uid();
    v_workspace_id uuid;
begin
    if v_user_id is null then
        raise exception 'authentication required' using errcode = '28000';
    end if;

    select wm.workspace_id into v_workspace_id
    from public.workspace_members wm
    where wm.user_id = v_user_id
    order by wm.created_at
    limit 1;

    if v_workspace_id is null then
        insert into public.workspaces(owner_user_id)
        values (v_user_id)
        returning id into v_workspace_id;

        insert into public.workspace_members(workspace_id, user_id, role)
        values (v_workspace_id, v_user_id, 'owner');
    end if;
    return v_workspace_id;
end;
$$;

revoke all on function public.ensure_personal_workspace() from public, anon;
grant execute on function public.ensure_personal_workspace() to authenticated;

create or replace function public.ingest_review_batch(
    p_workspace_id uuid,
    p_product jsonb,
    p_reviews jsonb,
    p_run jsonb,
    p_idempotency_key text
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_marketplace text := lower(trim(p_product->>'marketplace'));
    v_asin text := upper(trim(p_product->>'asin'));
    v_review_count integer := 0;
begin
    if p_workspace_id not in (select private.writable_workspace_ids()) then
        raise exception 'workspace access denied' using errcode = '42501';
    end if;
    if v_marketplace = '' or v_asin = '' then
        raise exception 'marketplace and asin are required' using errcode = '22023';
    end if;

    insert into public.ingest_receipts(workspace_id, idempotency_key)
    values (p_workspace_id, p_idempotency_key)
    on conflict do nothing;
    if not found then
        return jsonb_build_object('duplicate_batch', true, 'reviews', 0);
    end if;

    insert into public.products(
        workspace_id, marketplace, asin, parent_asin, title, note,
        added_at, last_scraped_at
    ) values (
        p_workspace_id, v_marketplace, v_asin,
        coalesce(p_product->>'parent_asin', ''),
        coalesce(p_product->>'title', ''),
        coalesce(p_product->>'note', ''), now(), now()
    )
    on conflict (workspace_id, marketplace, asin) do update set
        parent_asin = case when excluded.parent_asin <> '' then excluded.parent_asin else public.products.parent_asin end,
        title = case when excluded.title <> '' then excluded.title else public.products.title end,
        note = case when excluded.note <> '' then excluded.note else public.products.note end,
        last_scraped_at = now();

    insert into public.reviews(
        workspace_id, marketplace, review_id, rating, title, content,
        reviewer_name, review_date, review_date_raw, verified_purchase,
        helpful_votes, review_url, image_urls, language, raw_payload,
        first_seen_at, last_seen_at
    )
    select
        p_workspace_id,
        coalesce(nullif(lower(trim(r->>'marketplace')), ''), v_marketplace),
        upper(trim(r->>'review_id')),
        nullif(r->>'rating', '')::numeric,
        coalesce(r->>'title', ''),
        coalesce(r->>'content', ''),
        coalesce(r->>'reviewer_name', ''),
        case when coalesce(r->>'review_date', '') ~ '^\d{4}-\d{2}-\d{2}$'
             then (r->>'review_date')::date else null end,
        coalesce(r->>'review_date_raw', ''),
        coalesce((r->>'verified_purchase')::boolean, false),
        coalesce((r->>'helpful_votes')::integer, 0),
        coalesce(r->>'review_url', ''),
        coalesce(r->'image_urls', '[]'::jsonb),
        nullif(r->>'language', ''),
        coalesce(r->'raw_payload', '{}'::jsonb),
        coalesce(nullif(r->>'first_seen_at', '')::timestamptz, now()),
        coalesce(nullif(r->>'last_seen_at', '')::timestamptz, now())
    from jsonb_array_elements(coalesce(p_reviews, '[]'::jsonb)) as r
    where coalesce(trim(r->>'review_id'), '') <> ''
    on conflict (workspace_id, marketplace, review_id) do update set
        rating = coalesce(excluded.rating, public.reviews.rating),
        title = case when excluded.title <> '' then excluded.title else public.reviews.title end,
        content = case when excluded.content <> '' then excluded.content else public.reviews.content end,
        reviewer_name = case when excluded.reviewer_name <> '' then excluded.reviewer_name else public.reviews.reviewer_name end,
        review_date = coalesce(excluded.review_date, public.reviews.review_date),
        review_date_raw = case when excluded.review_date_raw <> '' then excluded.review_date_raw else public.reviews.review_date_raw end,
        verified_purchase = public.reviews.verified_purchase or excluded.verified_purchase,
        helpful_votes = greatest(public.reviews.helpful_votes, excluded.helpful_votes),
        review_url = case when excluded.review_url <> '' then excluded.review_url else public.reviews.review_url end,
        image_urls = case when excluded.image_urls <> '[]'::jsonb then excluded.image_urls else public.reviews.image_urls end,
        language = coalesce(excluded.language, public.reviews.language),
        raw_payload = excluded.raw_payload,
        last_seen_at = excluded.last_seen_at;
    get diagnostics v_review_count = row_count;

    insert into public.product_reviews(
        workspace_id, marketplace, asin, review_id, star_filter,
        page_number, first_seen_at, last_seen_at
    )
    select
        p_workspace_id, v_marketplace, v_asin, upper(trim(r->>'review_id')),
        coalesce(r->>'star_filter', ''), nullif(r->>'page_number', '')::integer,
        coalesce(nullif(r->>'first_seen_at', '')::timestamptz, now()),
        coalesce(nullif(r->>'last_seen_at', '')::timestamptz, now())
    from jsonb_array_elements(coalesce(p_reviews, '[]'::jsonb)) as r
    where coalesce(trim(r->>'review_id'), '') <> ''
    on conflict (workspace_id, marketplace, asin, review_id) do update set
        star_filter = case when excluded.star_filter <> '' then excluded.star_filter else public.product_reviews.star_filter end,
        page_number = coalesce(excluded.page_number, public.product_reviews.page_number),
        last_seen_at = excluded.last_seen_at;

    if coalesce(p_run, '{}'::jsonb) <> '{}'::jsonb then
        insert into public.collection_runs(
            workspace_id, asin, marketplace, started_at, finished_at,
            new_reviews, duplicate_reviews, status, error
        ) values (
            p_workspace_id, v_asin, v_marketplace,
            coalesce(nullif(p_run->>'started_at', '')::timestamptz, now()),
            coalesce(nullif(p_run->>'finished_at', '')::timestamptz, now()),
            coalesce((p_run->>'new_reviews')::integer, 0),
            coalesce((p_run->>'duplicate_reviews')::integer, 0),
            case when p_run->>'status' in ('ok', 'partial', 'failed') then p_run->>'status' else 'ok' end,
            coalesce(p_run->>'error', '')
        );
    end if;

    return jsonb_build_object('duplicate_batch', false, 'reviews', v_review_count);
end;
$$;

create or replace function public.list_product_stats(p_workspace_id uuid)
returns table(
    asin text, marketplace text, title text, last_scraped_at timestamptz,
    review_count bigint, avg_rating numeric
)
language sql stable security invoker set search_path = ''
as $$
    select p.asin, p.marketplace, p.title, p.last_scraped_at,
           count(pr.review_id), round(avg(r.rating), 2)
    from public.products p
    left join public.product_reviews pr
      on pr.workspace_id=p.workspace_id and pr.marketplace=p.marketplace and pr.asin=p.asin
    left join public.reviews r
      on r.workspace_id=pr.workspace_id and r.marketplace=pr.marketplace and r.review_id=pr.review_id
    where p.workspace_id=p_workspace_id
    group by p.workspace_id, p.asin, p.marketplace, p.title, p.last_scraped_at, p.added_at
    order by p.added_at
$$;

create or replace function public.search_reviews(
    p_workspace_id uuid,
    p_asin text default null,
    p_rating integer default null,
    p_keyword text default null,
    p_limit integer default 500,
    p_offset integer default 0
)
returns table(
    asin text, review_id text, rating numeric, star_filter text,
    review_date date, review_date_raw text, reviewer_name text,
    title text, content text, verified_purchase boolean, helpful_votes integer,
    review_url text, image_urls jsonb, first_seen_at timestamptz, last_seen_at timestamptz
)
language sql stable security invoker set search_path = ''
as $$
    select pr.asin, r.review_id, r.rating, pr.star_filter,
           r.review_date, r.review_date_raw, r.reviewer_name,
           r.title, r.content, r.verified_purchase, r.helpful_votes,
           r.review_url, r.image_urls, r.first_seen_at, r.last_seen_at
    from public.product_reviews pr
    join public.reviews r
      on r.workspace_id=pr.workspace_id and r.marketplace=pr.marketplace and r.review_id=pr.review_id
    where pr.workspace_id=p_workspace_id
      and (p_asin is null or pr.asin=p_asin)
      and (p_rating is null or round(r.rating)::integer=p_rating)
      and (p_keyword is null or r.title ilike '%' || p_keyword || '%' or r.content ilike '%' || p_keyword || '%')
    order by coalesce(r.review_date::timestamptz, r.first_seen_at) desc
    limit least(greatest(p_limit, 1), 5000)
    offset greatest(p_offset, 0)
$$;

create or replace function public.get_workspace_summary(p_workspace_id uuid)
returns jsonb
language sql stable security invoker set search_path = ''
as $$
    select jsonb_build_object(
        'product_count', (select count(*) from public.products where workspace_id=p_workspace_id),
        'review_count', (select count(*) from public.reviews where workspace_id=p_workspace_id)
    )
$$;

revoke all on function public.ingest_review_batch(uuid, jsonb, jsonb, jsonb, text) from public, anon;
revoke all on function public.list_product_stats(uuid) from public, anon;
revoke all on function public.search_reviews(uuid, text, integer, text, integer, integer) from public, anon;
revoke all on function public.get_workspace_summary(uuid) from public, anon;
grant execute on function public.ingest_review_batch(uuid, jsonb, jsonb, jsonb, text) to authenticated;
grant execute on function public.list_product_stats(uuid) to authenticated;
grant execute on function public.search_reviews(uuid, text, integer, text, integer, integer) to authenticated;
grant execute on function public.get_workspace_summary(uuid) to authenticated;

revoke all on public.workspaces, public.workspace_members, public.products,
    public.reviews, public.product_reviews, public.collection_runs,
    public.ingest_receipts, public.review_analysis from anon;
grant select, insert, update, delete on public.workspaces, public.workspace_members,
    public.products, public.reviews, public.product_reviews, public.collection_runs,
    public.ingest_receipts, public.review_analysis to authenticated;
