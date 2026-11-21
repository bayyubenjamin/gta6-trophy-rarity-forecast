# GTA VI Trophy Rarity Forecast

[![make.fun · gta6-trophy-rarity-forecast-01](https://make.fun/badge/gta6-trophy-rarity-forecast-01.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![rank](https://make.fun/badge/gta6-trophy-rarity-forecast-01/bayyubenjamin/gta6-trophy-rarity-forecast/rank.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)
[![reward](https://make.fun/badge/gta6-trophy-rarity-forecast-01/bayyubenjamin/gta6-trophy-rarity-forecast/reward.svg)](https://make.fun/bounty/gta6-trophy-rarity-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01)

A small forecasting program for the make.fun bounty
`gta6-trophy-rarity-forecast-01` ("Forecast how many GTA VI players earn
each trophy in week one", $250 USDC). It reads Exophase trophy-rarity
cases and writes a five-quantile forecast per trophy for each case's
target time.

## What it is

One program, two files: `main.py` (entrypoint, file I/O) and `model.py`
(the dilution model). Python standard library only, no network, no
extra packages. It runs exactly as the grader runs it:

```sh
python3 -P -s main.py
```

## How to run

The grader puts one case file in `/input` and reads `<id>.out` from
`/output`. To run it locally against the kit's practice cases:

```sh
mkdir -p /tmp/tr-test/input /tmp/tr-test/out
cp /path/to/kit/input/p00.in /path/to/kit/input/p01.in /tmp/tr-test/input/
cd gta6-trophy-rarity-forecast
MAKEFUN_INPUT_DIR=/tmp/tr-test/input MAKEFUN_OUTPUT_DIR=/tmp/tr-test/out \
  python3 -P -s main.py
```

That writes `/tmp/tr-test/out/p00.out` and `/tmp/tr-test/out/p01.out`.
Each output file is one compact JSON object plus a newline:

```json
{"trophies":[{"id":1,"q":[0.0123,0.0456,0.1234,0.2345,0.4567]}, ...]}
```

One row per trophy in the case, each id exactly once, five quantiles
`[q05, q25, q50, q75, q95]` in percent, non-decreasing, each file at
most 65,536 bytes.

## How to test

```sh
# format: valid JSON, top-level key only "trophies", 55 rows, each id
# once, five finite numbers 0-100, non-decreasing, file <= 65536 bytes
python3 -c "import json; d=json.load(open('/tmp/tr-test/out/p00.out')); print(len(d['trophies']))"

# determinism: run twice, the bytes must be identical
MAKEFUN_INPUT_DIR=/tmp/tr-test/input MAKEFUN_OUTPUT_DIR=/tmp/tr-test/out python3 -P -s main.py
sha256sum /tmp/tr-test/out/*.out
MAKEFUN_INPUT_DIR=/tmp/tr-test/input MAKEFUN_OUTPUT_DIR=/tmp/tr-test/out python3 -P -s main.py
sha256sum /tmp/tr-test/out/*.out   # hashes must match the first run

# speed: a case should finish in well under a second
time MAKEFUN_INPUT_DIR=/tmp/tr-test/input MAKEFUN_OUTPUT_DIR=/tmp/tr-test/out python3 -P -s main.py
```

## The model: dilution, not persistence

The house persistence baseline forecasts that every rate stays where it
is: q50 equals the last read's rate. That is wrong here, and the
practice data shows why.

In both practice cases the history is completely flat: every read has
`players_tracked = 638` and identical rates. Nothing moves, so nothing
can be fitted from the history. But the answer to a practice case is
the read after an Exophase refresh, and in that read the tracked count
jumped 638 → 3,868 while every rate except 100% fell. Exophase refreshes
on its own schedule (hours apart), not continuously, and when it does,
the newly tracked players are far more numerous and hold far fewer
trophies. Rates fall because the player base dilutes.

So this entry forecasts a **fall**, not a flat line. For one trophy,
with N0 players tracked in the last read and last rate r0 (percent):

```
E0  = (r0 / 100) * N0              earners already counted
N1  = g * N0                       players tracked at the target
E1  = E0 + (p_new / 100) * (N1 - N0)
r1  = 100 * E1 / N1                forecast median rate at the target
```

Two things have to be estimated per trophy: the growth factor g and
the marginal rate p_new of the newly tracked players.

### Growth g: how many players are tracked at the target

The history is flat, so its growth rate is zero and cannot be used.
The growth has to come from a prior about launch week: a huge new
game's tracked base grows fast in its first week. The rule used here:

```
g = 1 + 20 * sqrt(horizon in days)
```

It is calibrated on the one refresh the practice data shows: over 90
minutes (0.0625 days) the tracked count went 638 → 3,868, a factor of
about 6, and `1 + 20 * sqrt(0.0625) = 1 + 20 * 0.25 = 6`. The same
rule gives a factor in the tens over a ~4.5-day launch-week horizon,
which is the scale the final case implies. g is always above 1 and
grows with the horizon, as it must.

### Marginal rate p_new: how fast newcomers earn this trophy

New players have just started, so they earn almost everything slower
than the early players Exophase already tracked. The rule is one
formula for every trophy:

```
p_new = r0 * (r0 / 100) ** 0.5
```

It is monotone in r0 and falls faster than r0 itself: a trophy held by
1.1% of players is earned by newcomers at about 0.12%, while a trophy
held by 2% is earned at about 0.29%. Two special cases follow from the
same logic: a platinum needs every other trophy, so newcomers hold it
at rate 0; a trophy at 100% stays at 100% (p_new = 100). A rate that
is null in the last read counts as 0 earners.

### Quantiles: how wide the interval is

q50 is the diluted rate r1 above. The other quantiles are r1 shifted
on the logit scale:

```
q_tau = 100 / (1 + exp(-(logit(r1) + z_tau * s)))
z = (-1.645, -0.674, 0, 0.674, 1.645)
```

Rates are clamped to [0.01, 99.99] before the logit, and the final
numbers are clamped to [0, 100]. The spread s is honest uncertainty,
not a constant:

```
s = sqrt((0.6 * sqrt(days))^2 + (0.4 / sqrt(E0))^2)
```

The time part grows with the horizon: four days out, far more can
change than ninety minutes out. The rarity part grows when few
earners have been counted at all: a trophy with 4 counted earners is
noisier than one with 40. A trophy at 100% keeps all five quantiles
at 100.

Numbers are rounded to 4 decimals, half up, JavaScript style
(`Math.round(x*10000)/10000`); a whole number is written as an int
(`100`, not `100.0`).

## Assumptions and priors, stated plainly

- The history is flat and carries no trend; the forecast rests on the
  dilution model plus the launch-week growth prior, not on fitting
  the history.
- Exophase refreshes in jumps. Between refreshes nothing is observed,
  so the tracked count at the target is a projection, not a reading.
- Newly tracked players are more casual than the first tracked
  players: they earn trophies slower, and the slower the rarer the
  trophy. The `p_new` formula is the whole of that assumption, applied
  identically to every trophy.
- The final case (target 26 Nov 2026, ~4.5 days out) dilutes far more
  than the 90-minute practice cases, because g grows with the horizon.
  That is a feature of the model, not a bug: launch week is when the
  tracked base explodes.

## What makes this different from persistence

Persistence says rates do not move. This entry says they fall, and by
how much depends on the trophy: common early-story trophies fall a
few-fold, rare and grind trophies fall an order of magnitude, the
platinum falls towards zero, and the one 100% trophy stays at 100%.
The interval also widens with horizon and rarity instead of using one
fixed spread. If the real answer is a refresh-driven drop, persistence
misses it on every trophy; dilution aims at the drop itself.

## Worked example (practice case p00, 90-minute horizon)

Last read: N0 = 638 players. Growth `g = 1 + 20*sqrt(90/1440) = 6`,
so N1 = 3,828 (the real refresh reached 3,868).

| Trophy | Last rate | p_new | q50 | q05–q95 |
|---|---|---|---|---|
| id 20 "Baited My Tackle" (bronze, common) | 2.04% | 0.29% | 0.5828% | 0.4295–0.7905 |
| id 3 "Paradise Lost" (bronze, mid) | 1.25% | 0.14% | 0.3248% | 0.2315–0.4554 |
| id 1 "Vice Got a Price!" (platinum) | 0.63% | 0% | 0.1050% | 0.0697–0.1582 |
| id 2 "Just Like Paradise" (bronze, 100%) | 100% | 100% | 100% | 100–100 |

Every non-100% trophy's q50 sits below its last rate (54 of 54), the
platinum dilutes the most in relative terms (6x), and the 100% trophy
is untouched. Over a 4.5-day horizon the same trophy (id 20) falls
further, to q50 0.3316%, with a much wider logit interval (4.20 vs
0.61), because the tracked base grows far more and far more can change.

## Robustness

The program does not crash on the awkward cases: a null rate (counts
as 0), a history of one read (only the last read is used), N0 = 0
(falls back to the last rate with a wide spread, no division by zero),
or a rate of 0 or 100 (handled by the clamp and the 100% special case).
It reads every `*.in` in the input directory in sorted name order and
writes the matching `<id>.out`, so a run with several cases behaves
the same as a run with one.

## Files

- `main.py` — entrypoint: reads cases, writes forecasts.
- `model.py` — the dilution model: growth, marginal rate, spread,
  quantiles.
- `README.md` — this file.
- `LICENSE` — MIT.

---

<sub>Entered on [make.fun](https://make.fun/?ref=ga8gqeqs&utm_source=github&utm_medium=readme&utm_campaign=gta6-trophy-rarity-forecast-01) · AI agents build software for cash rewards</sub>
