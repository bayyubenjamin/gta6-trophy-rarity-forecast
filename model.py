"""Dilution forecast for GTA VI trophy rarity.

The core idea: Exophase's tracked-player count jumps when it refreshes,
and the new players it picks up have earned far fewer trophies than the
early players it already tracked. So a trophy's earn rate does not stay
put -- it gets diluted downward as the tracked base grows.

For one trophy, with N0 players tracked in the last read and a last rate
r0 (percent):

    E0  = (r0 / 100) * N0            earners already counted
    N1  = g * N0                     players tracked at the target
    E1  = E0 + (p_new / 100) * (N1 - N0)
    r1  = 100 * E1 / N1              forecast median rate at the target

where g is a horizon-dependent growth multiplier (g > 1, larger for a
longer horizon) and p_new is the rate at which the newly tracked players
earn this trophy. p_new is small for rare trophies and near r0 for the
common early ones, so rare trophies dilute the most.

Quantiles come from a logit-normal spread around r1: q_tau is r1 shifted
by z_tau * s on the logit scale, with s growing for longer horizons and
for trophies with fewer counted earners. That spread is the honest
uncertainty about the growth and the marginal rate.

Only the Python standard library is used. Everything here is pure
arithmetic on the case dict -- no network, no files, no clock, no
randomness -- so the same input always gives the same output.
"""

import math

# Quantile levels the contest scores, and the standard-normal quantile
# at each of them.
LEVELS = (0.05, 0.25, 0.5, 0.75, 0.95)
Z_SCORES = (-1.645, -0.674, 0.0, 0.674, 1.645)

# Rate bounds (percent) used before taking a logit, and for the final
# numbers. A rate of exactly 0 or 100 has no finite logit, so the
# working range is kept just inside.
LO_CLAMP = 0.01
HI_CLAMP = 99.99

# Growth of the tracked-player base: N1 = N0 * (1 + GROWTH_SLOPE * sqrt(days)).
# Calibrated on the one refresh the practice data shows: in 90 minutes
# (0.0625 days) the tracked count went 638 -> 3868, a factor of about 6,
# and sqrt(0.0625) = 0.25, so a slope of 20 gives 1 + 20 * 0.25 = 6.
# The same rule gives a factor in the tens over a 4.5-day launch-week
# horizon, which is the scale the launch implies.
GROWTH_SLOPE = 20.0

# Marginal rate for newly tracked players: p_new = r0 * (r0 / 100) ** P_EXP.
# The exponent makes p_new fall faster than r0 itself, so a trophy only
# 1% of players hold is earned by newcomers at roughly a tenth of that
# rate, while a trophy everyone holds stays at 100%. A platinum needs
# every other trophy, so newcomers essentially never hold it: p_new = 0.
P_EXP = 0.5

# Logit spread. One part grows with the horizon (the farther out, the
# less certain the growth and the marginal rate are); the other part
# grows when few earners have been counted at all. They combine in
# quadrature, so a trophy that is both far out and rarely earned gets
# the widest interval, and a common trophy seen many times gets a
# narrow one.
TIME_SPREAD = 0.6
RARE_SPREAD = 0.4


def _clamp_pct(pct):
    """Keep a percent inside the working range for logit math."""
    if pct < LO_CLAMP:
        return LO_CLAMP
    if pct > HI_CLAMP:
        return HI_CLAMP
    return pct


def _logit_pct(pct):
    """Logit of a percent (0..100), with the percent clamped first."""
    p = _clamp_pct(pct) / 100.0
    return math.log(p / (1.0 - p))


def _pct_from_logit(x):
    """Inverse logit, back to a percent in 0..100."""
    return 100.0 / (1.0 + math.exp(-x))


def _round_js4(x):
    """Round to 4 decimals, half up, the way JavaScript rounds.

    Math.round(x * 10000) / 10000, for the non-negative numbers we
    forecast. A whole result comes back as an int so the JSON writer
    prints 100 rather than 100.0.
    """
    scaled = x * 10000.0
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 10000.0
    if value == int(value):
        return int(value)
    return value


def growth_multiplier(horizon_minutes):
    """Factor by which the tracked-player base grows over the horizon.

    horizon_minutes is the case's horizon; the multiplier is
    1 + GROWTH_SLOPE * sqrt(days), so it is 1 at zero horizon, about 6
    over 90 minutes, and in the tens over a 4.5-day launch week.
    """
    days = horizon_minutes / 1440.0
    if days <= 0.0:
        return 1.0
    return 1.0 + GROWTH_SLOPE * math.sqrt(days)


def new_player_rate(last_rate, tier):
    """Rate (percent) at which newly tracked players earn this trophy.

    Platinum is special: it needs every other trophy, so newcomers
    hold it at rate zero. A trophy everyone already holds stays at
    100%. Everything else follows r0 * (r0/100)**P_EXP, which is
    monotone in r0 and much smaller than r0 for rare trophies.
    """
    if tier == "platinum":
        return 0.0
    if last_rate is None:
        return 0.0
    if last_rate >= 100.0:
        return 100.0
    if last_rate <= 0.0:
        return 0.0
    return last_rate * ((last_rate / 100.0) ** P_EXP)


def logit_spread(horizon_minutes, earners_counted):
    """Logit standard deviation s for this trophy and horizon.

    The time part is TIME_SPREAD * sqrt(days): the same random-walk
    shape the house persistence baseline uses, a touch wider because
    this model also has to guess the growth. The rarity part is
    RARE_SPREAD / sqrt(earners): with only a handful of counted
    earners the rate itself is noisy, so the interval widens.
    """
    days = horizon_minutes / 1440.0
    if days < 0.0:
        days = 0.0
    time_part = TIME_SPREAD * math.sqrt(days)
    base = earners_counted if earners_counted > 1.0 else 1.0
    rare_part = RARE_SPREAD / math.sqrt(base)
    return math.sqrt(time_part * time_part + rare_part * rare_part)


def trophy_quantiles(players_now, last_rate, tier, horizon_minutes):
    """Five quantiles [q05, q25, q50, q75, q95] for one trophy.

    players_now is N0 from the last read, last_rate is r0 (percent,
    None counts as 0). The median is the diluted rate r1; the other
    quantiles are r1 shifted by z_tau * s on the logit scale. A trophy
    at 100% stays at 100% on every quantile.
    """
    rate = 0.0 if last_rate is None else float(last_rate)
    if rate >= 100.0:
        return [100, 100, 100, 100, 100]
    if rate < 0.0:
        rate = 0.0

    if players_now is None or players_now <= 0:
        # No tracked base to dilute from: fall back to the last rate
        # itself, with a wide spread that admits we know little. The
        # extra 1.0 inside the spread is a flat ignorance term, not a
        # count of earners.
        median = rate
        time_part = TIME_SPREAD * math.sqrt(max(horizon_minutes, 0.0) / 1440.0)
        spread = math.sqrt(time_part * time_part + 1.0)
    else:
        n0 = float(players_now)
        earners = (rate / 100.0) * n0
        growth = growth_multiplier(horizon_minutes)
        n1 = growth * n0
        p_new = new_player_rate(rate, tier)
        earners_target = earners + (p_new / 100.0) * (n1 - n0)
        median = 100.0 * earners_target / n1
        spread = logit_spread(horizon_minutes, earners)

    if median >= 100.0:
        return [100, 100, 100, 100, 100]
    # A median of zero (nobody earned it, nobody new is expected to)
    # goes through the same logit path: the clamp in _logit_pct keeps
    # every quantile finite, small, and ordered around 0.01.
    centre = _logit_pct(median)
    out = []
    for z in Z_SCORES:
        q = _pct_from_logit(centre + z * spread)
        if q < 0.0:
            q = 0.0
        if q > 100.0:
            q = 100.0
        out.append(_round_js4(q))
    # Rounding can only tie neighbours, never reverse them, but guard
    # the ordering explicitly so the output is non-decreasing by
    # construction.
    for i in range(1, len(out)):
        if out[i] < out[i - 1]:
            out[i] = out[i - 1]
    return out


def forecast_all_trophies(case):
    """Forecast every trophy in a case dict, in the case's own order.

    Returns {"trophies": [{"id": ..., "q": [q05, q25, q50, q75, q95]}, ...]}
    with one row per trophy, each id exactly once, and no other keys.
    The last read of the history supplies N0 and each trophy's r0; a
    null rate counts as 0 earners for that trophy.
    """
    horizon = case["horizon_minutes"]
    history = case["history"]
    if history:
        last = history[-1]
        players_now = last.get("players_tracked")
        rates = last.get("rates") or []
    else:
        players_now = 0
        rates = []

    rows = []
    for i, trophy in enumerate(case["trophies"]):
        rate = rates[i] if i < len(rates) else None
        rows.append({
            "id": trophy["id"],
            "q": trophy_quantiles(players_now, rate, trophy.get("tier"), horizon),
        })
    return {"trophies": rows}
