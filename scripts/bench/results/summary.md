# Card-play benchmark: results

Figures are a mean per board ± one standard error. Tricks given away are against double dummy.

| setup | boards | declarer | defence | lead | IMPs a board against A | calculated cards | on 12 layouts | run |
|---|---|---|---|---|---|---|---|---|
| A | 60 | 0.42 ±0.07 | 0.50 ±0.09 | 0.15 ±0.06 | baseline | 2519 | 521 (21%) | 20 min |
| B | 60 | 0.42 ±0.07 | 0.50 ±0.09 | 0.15 ±0.06 | -0.02 ±0.02 | 2516 | 521 (21%) | 30 min |
| C | 60 | 0.48 ±0.08 | 0.50 ±0.09 | 0.15 ±0.06 | -0.03 ±0.15 | 2517 | 507 (20%) | 44 min |
| D | 60 | 0.93 ±0.12 | 0.82 ±0.11 | 0.15 ±0.06 | -2.40 ±0.56 | 2490 | 534 (21%) | 38 min |

## Against the baseline, board by board

| setup | declarer tricks | defence tricks | lead tricks | IMPs | won / lost / flat |
|---|---|---|---|---|---|
| B | +0.00 ±0.00, within the noise | +0.00 ±0.00, within the noise | +0.00 ±0.00, within the noise | -0.02 ±0.02, within the noise (about 241 boards to settle) | 0 / 1 / 59 |
| C | +0.07 ±0.04, within the noise (about 88 boards to settle) | +0.00 ±0.04, within the noise | +0.00 ±0.00, within the noise | -0.03 ±0.15, within the noise (about 4634 boards to settle) | 2 / 2 / 56 |
| D | +0.52 ±0.12, larger than the noise | +0.32 ±0.08, larger than the noise | +0.00 ±0.00, within the noise | -2.40 ±0.56, larger than the noise | 3 / 29 / 28 |

## B against A, the same question at every position of A's play

3 of 3120 cards differ (3 of 2476 where there was a choice), on 3 of 60 boards.
Answering those questions took B 570 s and had taken A 1179 s.
