# The run of 2026-10-12

60 boards, the same for every setup, PIMC off. The baseline bid each deal once
(`data/deals60.json`: none passed out; contracts from the one level to a grand slam, two
doubled; 45 of the 60 make double dummy). `summary.md` is the table; this is how it was made.

## The four setups

```text
A  today's production settings        engine: origin/main 6664842b, default_api.conf unchanged
B  A on the ONNX models               same engine; the 17 model paths point at models/onnx
C  A with sample_boards_for_play x2   same engine; 5000 -> 10000
D  A with the net fallback on         engine: origin/main 6664842b merged with
                                      origin/feature/net-fallback-and-budget 6836efcd (merges
                                      cleanly; a local checkout, on no branch)
                                      card_min_layouts 50, card_min_quality 0.8 - the values
                                      that commit names as its starting ones
                                      card_budget_seconds 0, lead_budget_seconds 0 - the time
                                      budget is a separate feature and is off
                                      sample_hands_opening_lead 200
```

D's settings file differs from A's by those six keys and nothing else.

## How long

All five ran side by side on this Mac (Apple M5 Max, 18 cores), 06:27:57 to 07:11:31, with
the load average between 2.4 and 7.9. Bidding the boards beforehand took 489 s, most of it
waiting: bids are paced to stay under BEN's own limit of 100 requests a minute.

```text
A, all four seats, 60 boards              1,203 s   A's own cards 1,179 s
B against A, two tables a board           1,799 s   B's own cards   574 s
C against A                               2,615 s   C's own cards 1,445 s
D against A                               2,282 s   D's own cards 1,090 s
B asked A's 3,120 questions                 591 s
```

Per calculated card, from each service's own `[robot-time]` line: A 396 ms of which 262 in the
networks, B 172 of which 37, C 505 of which 338, D 368 of which 252.

**These times are this machine's and were taken with other runs going on beside them.** They
say B is quicker than A here; they do not say by how much on the service's two shared CPUs.

## Two things to know before trusting a difference

- **The baseline does not quite repeat itself.** Where a match table was still card for card
  the baseline's own play, a second baseline service asked for the next card gave a different
  one 2 times in 3,044 (B's match), 1 in 2,594 (C's) and 0 in 1,499 (D's). So about one card in
  a thousand differs with nothing changed, and a difference of that size between two setups
  is not a difference.
- **Tricks given away are against double dummy**, which sees all four hands. A card that
  loses nothing double dummy can still be the wrong card at the table.

## What it found

- **B plays A's cards.** 3 of 3,120 answers differ - the same order as the baseline against
  itself - and the match is 59 boards flat and one lost by an overtrick.
- **C changes almost nothing.** 507 cards on 12 layouts against 521, 56 of 60 boards flat,
  -2 IMPs over the 60, and it thinks about a quarter longer.
- **D is worse, and by more than the noise.** At 50 layouts and 0.8 fit the fallback hands
  1,653 of its 2,473 cards with a choice to the net; it loses 29 boards and wins 3, 144 IMPs
  over the 60.
- **A card on 12 layouts is not where the baseline loses its tricks.** 8 tricks over 521 such
  cards (0.015 a card), against 38 over the other 1,998 calculated cards (0.019).
