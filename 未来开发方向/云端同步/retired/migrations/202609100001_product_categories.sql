-- ReviewCollector: Amazon small-category taxonomy and product associations.
-- Run after 202608290001_initial.sql.

begin;

create table if not exists public.categories (
    workspace_id uuid not null references public.workspaces(id) on delete cascade,
    marketplace text not null,
    category_id text not null,
    category_name text not null default '',
    category_path jsonb not null default '[]'::jsonb,
    first_seen_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    primary key (workspace_id, marketplace, category_id)
);

create table if not exists public.product_categories (
    workspace_id uuid not null,
    marketplace text not null,
    asin text not null,
    category_id text not null,
    is_primary boolean not null default false,
    is_current boolean not null default true,
    source text not null default 'breadcrumb',
    first_seen_at timestamptz not null default now(),
    last_seen_at timestamptz not null default now(),
    primary key (workspace_id, marketplace, asin, category_id),
    foreign key (workspace_id, marketplace, asin)
        references public.products(workspace_id, marketplace, asin) on delete cascade,
    foreign key (workspace_id, marketplace, category_id)
        references public.categories(workspace_id, marketplace, category_id) on delete cascade
);

create unique index if not exists product_categories_one_current_primary_idx
    on public.product_categories(workspace_id, marketplace, asin)
    where is_primary and is_current;
create index if not exists product_categories_category_idx
    on public.product_categories(workspace_id, marketplace, category_id)
    where is_current;

alter table public.categories enable row level security;
alter table public.product_categories enable row level security;

drop policy if exists categories_member_read on public.categories;
drop policy if exists categories_writer_manage on public.categories;
create policy categories_member_read on public.categories
    for select to authenticated
    using (workspace_id in (select private.user_workspace_ids()));
create policy categories_writer_manage on public.categories
    for all to authenticated
    using (workspace_id in (select private.writable_workspace_ids()))
    with check (workspace_id in (select private.writable_workspace_ids()));

drop policy if exists product_categories_member_read on public.product_categories;
drop policy if exists product_categories_writer_manage on public.product_categories;
create policy product_categories_member_read on public.product_categories
    for select to authenticated
    using (workspace_id in (select private.user_workspace_ids()));
create policy product_categories_writer_manage on public.product_categories
    for all to authenticated
    using (workspace_id in (select private.writable_workspace_ids()))
    with check (workspace_id in (select private.writable_workspace_ids()));

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
    v_categories jsonb := case
        when jsonb_typeof(p_product->'categories') = 'array'
        then p_product->'categories'
        else '[]'::jsonb
    end;
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

    if jsonb_array_length(v_categories) > 0 then
        update public.product_categories
        set is_primary = false, is_current = false
        where workspace_id = p_workspace_id
          and marketplace = v_marketplace
          and asin = v_asin;

        insert into public.categories(
            workspace_id, marketplace, category_id, category_name,
            category_path, first_seen_at, last_seen_at
        )
        select
            p_workspace_id,
            v_marketplace,
            trim(c->>'category_id'),
            coalesce(c->>'category_name', ''),
            case when jsonb_typeof(c->'category_path') = 'array'
                 then c->'category_path' else '[]'::jsonb end,
            now(), now()
        from jsonb_array_elements(v_categories) as c
        where coalesce(trim(c->>'category_id'), '') <> ''
        on conflict (workspace_id, marketplace, category_id) do update set
            category_name = case when excluded.category_name <> '' then excluded.category_name else public.categories.category_name end,
            category_path = case when excluded.category_path <> '[]'::jsonb then excluded.category_path else public.categories.category_path end,
            last_seen_at = excluded.last_seen_at;

        insert into public.product_categories(
            workspace_id, marketplace, asin, category_id, is_primary,
            is_current, source, first_seen_at, last_seen_at
        )
        select
            p_workspace_id,
            v_marketplace,
            v_asin,
            trim(c->>'category_id'),
            coalesce(nullif(c->>'is_primary', '')::boolean, false),
            true,
            coalesce(nullif(trim(c->>'source'), ''), 'breadcrumb'),
            now(), now()
        from jsonb_array_elements(v_categories) as c
        where coalesce(trim(c->>'category_id'), '') <> ''
        on conflict (workspace_id, marketplace, asin, category_id) do update set
            is_primary = excluded.is_primary,
            is_current = true,
            source = excluded.source,
            last_seen_at = excluded.last_seen_at;
    end if;

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

drop function if exists public.list_product_stats(uuid);
create function public.list_product_stats(p_workspace_id uuid)
returns table(
    asin text, marketplace text, title text, last_scraped_at timestamptz,
    review_count bigint, avg_rating numeric,
    category_id text, category_name text, category_path jsonb
)
language sql stable security invoker set search_path = ''
as $$
    select p.asin, p.marketplace, p.title, p.last_scraped_at,
           count(pr.review_id), round(avg(r.rating), 2),
           category.category_id, category.category_name, category.category_path
    from public.products p
    left join public.product_reviews pr
      on pr.workspace_id=p.workspace_id and pr.marketplace=p.marketplace and pr.asin=p.asin
    left join public.reviews r
      on r.workspace_id=pr.workspace_id and r.marketplace=pr.marketplace and r.review_id=pr.review_id
    left join lateral (
        select c.category_id, c.category_name, c.category_path
        from public.product_categories pc
        join public.categories c
          on c.workspace_id=pc.workspace_id
         and c.marketplace=pc.marketplace
         and c.category_id=pc.category_id
        where pc.workspace_id=p.workspace_id
          and pc.marketplace=p.marketplace
          and pc.asin=p.asin
          and pc.is_current
        order by pc.is_primary desc, pc.first_seen_at
        limit 1
    ) as category on true
    where p.workspace_id=p_workspace_id
    group by p.workspace_id, p.asin, p.marketplace, p.title,
             p.last_scraped_at, p.added_at,
             category.category_id, category.category_name, category.category_path
    order by p.added_at
$$;

revoke all on public.categories, public.product_categories from anon;
grant select, insert, update, delete on public.categories, public.product_categories to authenticated;
revoke all on function public.list_product_stats(uuid) from public, anon;
grant execute on function public.list_product_stats(uuid) to authenticated;

commit;
