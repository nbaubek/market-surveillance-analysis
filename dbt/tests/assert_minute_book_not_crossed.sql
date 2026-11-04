-- Quote sanity: the reconstructed book must never cross
-- (best_bid > best_ask). Locked markets (bid = ask) are legal Nasdaq
-- states and are allowed; crossing is not. One-sided minutes (NULL
-- side) are legal — early pre-market quoting.
select *
from {{ ref('minute_book_metrics') }}
where best_bid is not null
  and best_ask is not null
  and best_bid > best_ask
