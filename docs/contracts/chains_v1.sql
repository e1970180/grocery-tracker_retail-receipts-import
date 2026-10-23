-- Chain reference, consumer contract chains_v1 1.1.0 (see chains_v1.md).
-- The admin runs this once per environment as the reference owner, then grants SELECT on
-- public.chains_v1 to that environment's writer role. No BEGIN/COMMIT here: the caller
-- decides the transaction (psql -1, or a test transaction that rolls back).

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
    seller_oibs text[] NOT NULL
        CONSTRAINT chains_seller_oibs_valid CHECK (
            coalesce(array_ndims(seller_oibs), 1) = 1
            AND array_position(seller_oibs, NULL) IS NULL
            AND cardinality(seller_oibs) > 0
            AND array_to_string(seller_oibs, ',') ~ '^[0-9]{11}(,[0-9]{11})*$'
            -- The length ties the groups to the elements, so one element holding a comma fails.
            AND length(array_to_string(seller_oibs, ',')) = 12 * cardinality(seller_oibs) - 1
        ),
    active boolean NOT NULL DEFAULT true
);

CREATE VIEW public.chains_v1 AS
SELECT chain_id, display_name, aliases, seller_oibs, active
FROM public.chains;

INSERT INTO public.chains (chain_id, display_name, aliases, seller_oibs, active) VALUES
    ('dm', 'dm', ARRAY['DM', 'dm'], ARRAY['94124811986'], true),
    ('kaufland', 'Kaufland', ARRAY['KAUFLAND', 'Kaufland'], ARRAY['47432874968'], true),
    ('lidl', 'Lidl', ARRAY['LIDL', 'Lidl'], ARRAY['66089976432'], true),
    ('mueller', 'Müller', ARRAY['MÜLLER', 'Müller', 'Muller'], ARRAY['84698789700'], true),
    ('spar', 'Spar', ARRAY['SPAR', 'Spar', 'INTERSPAR'], ARRAY['46108893754'], true);
