-- Chain reference, consumer contract chains_v1 1.2.0 (see chains_v1.md).
-- Reference copy for dev and tests. In shared environments grocery-tracker/common owns the
-- chains table, its DDL and migrations; this file only shows the shape this service reads.
-- Grant SELECT on public.chains_v1 to the environment's writer role afterwards. No BEGIN/COMMIT
-- here: the caller decides the transaction (psql -1, or a test transaction that rolls back).

CREATE TABLE public.chains (
    chain_id text PRIMARY KEY
        CONSTRAINT chains_chain_id_slug CHECK (chain_id ~ '^[a-z][a-z0-9_]{0,31}$')
        CONSTRAINT chains_chain_id_not_reserved CHECK (chain_id NOT IN ('other', 'unreadable')),
    display_name text NOT NULL
        CONSTRAINT chains_display_name_not_empty CHECK (btrim(display_name) <> ''),
    aliases text[] NOT NULL DEFAULT '{}'
        CONSTRAINT chains_aliases_valid CHECK (
            coalesce(array_ndims(aliases), 1) = 1
            AND array_position(aliases, NULL) IS NULL
            AND '' <> ALL (aliases)
        ),
    -- No foreign key: public provides country codes by convention only.
    country_code text NOT NULL
        CONSTRAINT chains_country_code_valid CHECK (country_code ~ '^[A-Z]{2}$'),
    tax_numbers text[]
        CONSTRAINT chains_tax_numbers_valid CHECK (
            tax_numbers IS NULL
            OR (
                coalesce(array_ndims(tax_numbers), 1) = 1
                AND array_position(tax_numbers, NULL) IS NULL
                -- A blank element shows up as an empty or whitespace-only piece of the joined text.
                AND (
                    cardinality(tax_numbers) = 0
                    OR array_to_string(tax_numbers, ',') !~ '(^|,)[[:space:]]*(,|$)'
                )
                -- No element may hold a comma, or the joined-text checks would misread it.
                AND length(replace(array_to_string(tax_numbers, ','), ',', ''))
                    = length(array_to_string(tax_numbers, ',')) - greatest(cardinality(tax_numbers) - 1, 0)
            )
        ),
    active boolean NOT NULL DEFAULT true,
    CONSTRAINT chains_hr_tax_numbers_oib CHECK (
        country_code <> 'HR'
        OR tax_numbers IS NULL
        OR cardinality(tax_numbers) = 0
        OR (
            array_to_string(tax_numbers, ',') ~ '^[0-9]{11}(,[0-9]{11})*$'
            -- The length ties the groups to the elements, so one element holding a comma fails.
            AND length(array_to_string(tax_numbers, ',')) = 12 * cardinality(tax_numbers) - 1
        )
    )
);

CREATE VIEW public.chains_v1 AS
SELECT chain_id, display_name, aliases, country_code, tax_numbers, active
FROM public.chains;

INSERT INTO public.chains (chain_id, display_name, aliases, country_code, tax_numbers, active) VALUES
    ('dm', 'dm', ARRAY['DM', 'dm'], 'HR', ARRAY['94124811986'], true),
    ('kaufland', 'Kaufland', ARRAY['KAUFLAND', 'Kaufland'], 'HR', ARRAY['47432874968'], true),
    ('lidl', 'Lidl', ARRAY['LIDL', 'Lidl'], 'HR', ARRAY['66089976432'], true),
    ('mueller', 'Müller', ARRAY['MÜLLER', 'Müller', 'Muller'], 'HR', ARRAY['84698789700'], true),
    ('spar', 'Spar', ARRAY['SPAR', 'Spar', 'INTERSPAR'], 'HR', ARRAY['46108893754'], true);
