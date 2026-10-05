"""
[ben-why] WHY A ROBOT PLAYED THE CARD IT DID.

Every decision BEN makes already computes its own reasoning - the net's score for each
candidate, what double dummy said over the samples, what PIMC said, and the named rule
that picked the winner. Almost all of it is thrown away: the HTTP response keeps only
the card, and `details=false` (what the site sends) strips even the candidates. So a
robot leading the king from K-J-x leaves nothing behind to argue with.

This writes ONE line per decision to stdout, which on Render is the log.

Two halves, because the reasoning lives in two places:

  * Most of it survives into CardResp / BidResp - candidates, `who`, the samples - so it
    is simply FORMATTED at the route, with no reach into the decision at all.

  * The rest never gets that far, and is recorded here as it happens:
      - the PIMC / BEN-DD / merged triple per card, which merge_candidate_cards()
        otherwise flattens into free text inside `msg`;
      - the cards DROPPED for scoring below pimc_trust_NN, which never become candidates
        and are therefore invisible in the response - the single most useful thing in the
        line, because a card BEN never considered looks identical to one it rejected.

Thread-local, so two decisions in flight cannot write into each other, and nothing is
kept between decisions: start() throws the previous one away. Every public method is
total - it cannot raise, and with no start() ever called it quietly does nothing, so the
paths that do not log (analysis, autoplay, the websocket server) pay one attribute lookup.
"""

import threading


def _sym(card):
    """
    A card as the RESPONSE spells it, because that is what the line is joined on.
    Accepts either a 0-51 code or a symbol already. Total: a decision must never fail
    because a log line could not name a card.
    """
    try:
        if isinstance(card, str):
            return card
        from objects import Card
        return Card.from_code(int(card)).symbol()
    except Exception:
        return str(card)


class Why:
    _local = threading.local()

    # ---- lifecycle ----

    @classmethod
    def start(cls, rid=None):
        cls._local.d = {'rid': rid or '-', 'facts': {}, 'cards': {}, 'dropped': []}

    @classmethod
    def _d(cls):
        return getattr(cls._local, 'd', None)

    @classmethod
    def get(cls):
        return cls._d() or {'rid': '-', 'facts': {}, 'cards': {}, 'dropped': []}

    # ---- recording ----

    @classmethod
    def note(cls, **facts):
        """Decision-level facts: the weight used, whether PIMC was rejected, and why."""
        d = cls._d()
        if d is not None:
            d['facts'].update(facts)

    @classmethod
    def card(cls, card, **fields):
        """Per-candidate numbers, merged by card as the stages produce them."""
        d = cls._d()
        if d is not None:
            try:
                d['cards'].setdefault(_sym(card), {}).update(fields)
            except Exception:
                pass

    @classmethod
    def dropped(cls, card, nn, threshold):
        """A legal card the neural network scored too low to be considered at all."""
        d = cls._d()
        if d is not None:
            try:
                d['dropped'].append((_sym(card), float(nn), float(threshold)))
            except Exception:
                pass


# ---------------------------------------------------------------------------
# FORMATTING
#
# One line, and it stays one line: newlines are stripped out of anything that
# came from a `who` or a `msg`, and the candidate list is capped so a thirteen
# card trick-one decision cannot run away.
# ---------------------------------------------------------------------------

MAX_CANDIDATES = 8


def _n(v, places=2):
    """A number, short, with no exponent and no numpy repr - or '-' if there isn't one."""
    if v is None:
        return '-'
    try:
        f = float(v)
    except (TypeError, ValueError):
        return '-'
    if f != f or f in (float('inf'), float('-inf')):
        return '-'
    return ('%.*f' % (places, f)).rstrip('0').rstrip('.') or '0'


def _clean(s):
    if s is None:
        return '-'
    return ' '.join(str(s).split()) or '-'


def _tail(items):
    shown = items[:MAX_CANDIDATES]
    out = ' | '.join(shown)
    if len(items) > MAX_CANDIDATES:
        out += ' | +%d more' % (len(items) - MAX_CANDIDATES)
    return out


def log_lead(result, seat, contract, hand, lead_accept_nn=None):
    """
    [ben-why] lead - one line for an opening lead.

    Everything here comes out of the CardResp the route already has, so this cannot
    perturb the decision: the net's score per card (insta_score), what double dummy made
    of it over the samples (expected tricks and the chance of beating the contract), how
    many samples those numbers rest on, and `who` - BEN's own name for the rule that
    chose. When that rule was the net's own confidence shortcut, the threshold it cleared
    is printed beside it, because "NN - best" on its own does not say how close it was.
    """
    try:
        w = Why.get()
        cands = result.get('candidates') or []
        n = len(result.get('samples') or [])
        who = _clean(result.get('who'))
        rule = who
        if who.startswith('NN - best') and lead_accept_nn is not None:
            top = cands[0].get('insta_score') if cands else None
            rule = 'NN-best nn=%s>lead_accept_nn=%s' % (_n(top, 3), _n(lead_accept_nn, 2))

        parts = []
        for c in cands:
            bits = ['%s nn=%s' % (c.get('card'), _n(c.get('insta_score'), 3))]
            for key, label in (('expected_tricks_dd', 'ddtricks'), ('expected_tricks_sd', 'sdtricks'),
                               ('p_make_contract', 'pmake'), ('expected_score_dd', 'score'),
                               ('expected_score_imp', 'imp'), ('expected_score_mp', 'mp')):
                if c.get(key) is not None:
                    bits.append('%s=%s' % (label, _n(c.get(key))))
            if c.get('msg'):
                bits.append('(%s)' % _clean(c.get('msg')))
            parts.append(' '.join(bits))

        print('[ben-why] lead rid=%s seat=%s contract=%s hand=%s card=%s rule=%s n=%d q=%s :: %s' % (
            w['rid'], seat, contract or '-', hand or '-', _clean(result.get('card')),
            rule, n, _clean(result.get('quality')), _tail(parts)), flush=True)
    except Exception:
        pass


def log_play(result, seat, trick_i, path):
    """
    [ben-why] play - one line for a card in the play.

    `path` is play_api's own verdict, so the two shortcuts that never reach a neural
    network at all - a forced singleton, and following with equals - are visible as
    themselves rather than as a decision with no numbers in it.

    The per-card numbers are the three engines side by side: nn is the play net, dd is
    BEN's double dummy over the samples, pimc is PIMC's own answer, and mrg is the
    weighted blend that was actually sorted on. Each is shown as tricks/make. When the
    merge threw PIMC out for the whole decision, pimc= says so and mrg equals dd.

    `drop=` is the part that is not in the response at any detail level: cards the play
    net scored below pimc_trust_NN are removed before scoring, so they never become
    candidates. A card BEN never considered and a card BEN considered and rejected look
    identical from outside, and this is the only place they are told apart.
    """
    try:
        w = Why.get()
        f = w['facts']
        rec = w['cards']
        cands = (result.get('candidates') or []) if isinstance(result, dict) else []
        n = len(result.get('samples') or []) if isinstance(result, dict) else 0

        if f.get('pimc_rejected'):
            pimc_state = 'rejected(%s)' % _clean(f.get('pimc_reject_reason'))
        elif f.get('pimc_weight') is not None:
            w_txt = _n(f.get('pimc_weight'), 2)
            pimc_state = 'used' if w_txt == '-' else 'used w=%s' % w_txt
        else:
            pimc_state = 'off'

        parts = []
        for c in cands:
            card = c.get('card')
            r = rec.get(card, {})
            bits = ['%s nn=%s' % (card, _n(c.get('insta_score'), 3))]
            # dd and pimc only exist when the merge ran; the BEN-DD-only path never
            # calls it. mrg always comes from the candidate itself, because that is
            # the number that was actually sorted on, adjustments and all.
            for key, label in (('dd', 'dd'), ('pimc', 'pimc')):
                t, m = r.get(key + '_tricks'), r.get(key + '_make')
                if t is not None or m is not None:
                    bits.append('%s=%s/%s' % (label, _n(t), _n(m)))
            bits.append('mrg=%s/%s' % (_n(c.get('expected_tricks_dd')), _n(c.get('p_make_contract'))))
            if c.get('expected_score_imp') is not None:
                bits.append('imp=%s' % _n(c.get('expected_score_imp')))
            if c.get('expected_score_mp') is not None:
                bits.append('mp=%s' % _n(c.get('expected_score_mp')))
            parts.append(' '.join(bits))

        drop = ','.join('%s:%s' % (c, _n(s, 3)) for c, s, _t in w['dropped'][:8])
        thr = w['dropped'][0][2] if w['dropped'] else None

        print('[ben-why] play rid=%s seat=%s trick=%s path=%s card=%s rule=%s pimc=%s playouts=%s n=%d q=%s :: %s%s' % (
            w['rid'], seat, trick_i, path,
            _clean(result.get('card')) if isinstance(result, dict) else '-',
            _clean(result.get('who') if isinstance(result, dict) else None),
            pimc_state, f.get('playouts', '-'), n,
            _clean(result.get('quality') if isinstance(result, dict) else None),
            _tail(parts) or '(no candidates)',
            (' :: drop<%s=%s' % (_n(thr, 3), drop)) if drop else ''), flush=True)
    except Exception:
        pass


def log_bid(result, seat, dealer, vul, ctx):
    """
    [ben-why] bid - one line for a call.

    search=yes/no is the fork that matters most: below interactive_no_search_threshold
    BEN takes the net's top call and never rolls anything out, so every simulated number
    below is absent and the net's score is the whole story. Samples only exist when the
    rollout ran, which is what marks the path.
    """
    try:
        w = Why.get()
        cands = result.get('candidates') or []
        n = len(result.get('samples') or [])
        parts = []
        for c in cands:
            bits = ['%s nn=%s' % (c.get('call'), _n(c.get('insta_score'), 3))]
            for key, label in (('expected_score', 'score'), ('expected_imp', 'imp'),
                               ('expected_mp', 'mp'), ('expected_tricks', 'tricks'),
                               ('adjustment', 'adj')):
                if c.get(key) is not None:
                    bits.append('%s=%s' % (label, _n(c.get(key))))
            if c.get('who'):
                bits.append('(%s)' % _clean(c.get('who')))
            parts.append(' '.join(bits))

        print('[ben-why] bid rid=%s seat=%s dealer=%s vul=%s ctx=%s call=%s rule=%s search=%s n=%d q=%s :: %s' % (
            w['rid'], seat, dealer or '-', vul if vul not in (None, '') else '-', ctx or '-',
            _clean(result.get('bid')), _clean(result.get('who')), 'yes' if n else 'no', n,
            _clean(result.get('quality')), _tail(parts) or '(no candidates)'), flush=True)
    except Exception:
        pass
