-- Interval sanity: an interval must end strictly after it starts
-- (sequence space). valid_to_seq NULL means "still live" and is fine.
-- An inverted or zero-length interval would corrupt any consumer's
-- point-in-time evaluation.
select *
from {{ ref('book_state') }}
where valid_to_seq is not null
  and valid_to_seq <= seq_from
