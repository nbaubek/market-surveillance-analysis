-- Replay invariant: a level's displayed quantity must never be negative.
-- A violation means a C subtracted from a level without sufficient
-- resting quantity — i.e., the attribution rule (C removes exactly
-- C.size at C.(side, price)) is broken somewhere upstream.
select *
from {{ ref('book_state') }}
where net_qty < 0
