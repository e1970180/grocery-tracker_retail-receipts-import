-- Chain reference, consumer contract chains_v1 1.0.0 (see chains_v1.md).
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
    active boolean NOT NULL DEFAULT true
);

CREATE VIEW public.chains_v1 AS
SELECT chain_id, display_name, aliases, active
FROM public.chains;

INSERT INTO public.chains (chain_id, display_name, aliases, active) VALUES
    ('dm', 'dm', ARRAY['DM', 'dm'], true),
    ('kaufland', 'Kaufland', ARRAY['KAUFLAND', 'Kaufland'], true),
    ('lidl', 'Lidl', ARRAY['LIDL', 'Lidl'], true),
    ('mueller', 'Müller', ARRAY['MÜLLER', 'Müller', 'Muller'], true),
    ('spar', 'Spar', ARRAY['SPAR', 'Spar', 'INTERSPAR'], true);
