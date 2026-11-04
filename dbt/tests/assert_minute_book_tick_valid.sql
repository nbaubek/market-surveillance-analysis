-- Tick sanity: with both sides present, the spread cannot be negative
-- (covered by the not-crossed test) and both quotes must sit on the
-- penny grid (Nasdaq displayed quotes for >$1 symbols are
-- penny-incremented; a sub-penny displayed quote means the replay
-- fabricated a price level).
select *
from {{ ref('minute_book_metrics') }}
where (best_bid is not null and cast(best_bid * 100 as integer) * 100 != cast(best_bid * 10000 as integer))
   or (best_ask is not null and cast(best_ask * 100 as integer) * 100 != cast(best_ask * 10000 as integer))
