"""On-sale stampede: every scenario mixed into one burst, then PASS/FAIL checks.

    ./burst.sh <BASE_URL> [--requests 2000] [--concurrency 200] [--seats N] [--ramp 3] [--admin-key KEY]

--seats sets the show's total seat count (default: auto, ~4 random requests per
random seat). The 31 scenario seats below always exist; the rest become R1..Rn.

Standard library only. The admin key (to create the show) comes from
--admin-key or ADMIN_API_KEY; default is the local docker-compose demo key.

Each scenario has its own seats, so scenarios can't affect each other's results:
  R*      random bookings, one seat each
  H1      hot seat: many users at once
  F1      small fight: 5 users at once
  B1      already booked before the burst: everyone gets 409
  P1-P3   bulk [P1,Px] where P1 is already booked: all-or-nothing, P2/P3 stay free
  T1,T2   one user, two separate bookings (different keys): both succeed
  K1      one user retries the same request 5x in parallel: one booking
  Q1,Q2   key used for Q1 before the burst, reused for Q2: 409
  L1-L5   user already holds 4 (limit), asks for a 5th: 409
  G1-G10  one user fires 10 parallel requests, limit 4: exactly 4 succeed
  D1-D4   overlapping multi-seat requests in opposite orders: no deadlock
  X1      body says user_id=someone-else: booked as the token's user
While the burst runs, a poller checks available + held + confirmed == total.

Every request sends its own X-Request-ID (burst<run>-<n>, "-r" on a resend), so
any failure listed in the report can be found in the server logs by that id.
Failures are also written to burst-<run>-failures.jsonl.

Network drops: if a reused connection breaks, the request is resent once on a
new connection (safe: it carries an idempotency key). If the first copy had
already reached the server, the server counted it too; the checks allow for
exactly that, so lost responses don't show up as false failures.

/metrics is compared before/after, so run it when nothing else hits the service.
"""

import argparse
import http.client
import json
import os
import random
import re
import ssl
import sys
import threading
import time
import urllib.parse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

LIMIT = 4
_local = threading.local()


def request(base, method, path, body=None, headers=None, request_id=None, ramp=0.0):
    """One HTTP call on this thread's kept-alive connection.

    Returns a dict: status (0 = no response), body, request_id (the id of the
    attempt that answered), resent (a broken reused connection was retried),
    first_error, and on failure: error + phase (connect / tls / send / response).
    """
    url = urllib.parse.urlsplit(base)
    data = json.dumps(body).encode() if body is not None else None
    out = {"status": 0, "body": None, "request_id": request_id, "resent": False, "first_error": None}

    if ramp and not getattr(_local, "started", False):
        # Spread the first connections over `ramp` seconds instead of opening
        # all of them in the same instant (avoids TLS handshake pile-ups).
        _local.started = True
        time.sleep(random.uniform(0, ramp))

    for attempt in (1, 2):
        rid = request_id if attempt == 1 or not request_id else f"{request_id}-r"
        hdrs = {"content-type": "application/json", **(headers or {})}
        if rid:
            hdrs["x-request-id"] = rid
        conn = getattr(_local, "conn", None)
        fresh = conn is None
        phase = "connect"
        try:
            if fresh:
                cls = http.client.HTTPSConnection if url.scheme == "https" else http.client.HTTPConnection
                conn = _local.conn = cls(url.hostname, url.port, timeout=60)
                conn.connect()
            phase = "send"
            conn.request(method, url.path.rstrip("/") + path, body=data, headers=hdrs)
            phase = "response"
            r = conn.getresponse()
            raw = r.read()
            out.update(status=r.status, request_id=r.headers.get("x-request-id", rid))
            try:
                out["body"] = json.loads(raw)
            except ValueError:
                out["body"] = raw.decode(errors="replace")
            return out
        except Exception as e:
            if isinstance(e, (ssl.SSLError, ssl.SSLCertVerificationError)) or "handshake" in str(e):
                phase = "tls" if phase == "connect" else phase
            error = f"{type(e).__name__}: {e}"
            conn.close()
            _local.conn = None
            if fresh or attempt == 2:
                out.update(error=error, phase=phase, request_id=rid)
                return out
            # A reused connection broke (often closed by the server/proxy while
            # idle). Resend once on a new connection; the idempotency key makes
            # this safe even if the first copy was already processed.
            out.update(resent=True, first_error=f"{phase}: {error}")
    return out


def metrics(base):
    r = request(base, "GET", "/metrics")
    if r["status"] != 200 or not isinstance(r["body"], str):
        return {}
    return {l.rsplit(" ", 1)[0]: float(l.rsplit(" ", 1)[1])
            for l in r["body"].splitlines() if l and not l.startswith("#")}


# Where a request failed tells you whether the server could have seen it.
PHASE_MEANING = {
    "connect": "could not open a TCP connection: never reached the server",
    "tls": "TLS handshake did not finish: never reached the server",
    "send": "connection broke while sending: may or may not have reached the server",
    "response": "sent, but no response came back: may have been processed by the server",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("base_url")
    ap.add_argument("--requests", type=int, default=2000, help="random + hot-seat requests (default 2000)")
    ap.add_argument("--concurrency", type=int, default=200, help="requests in flight at once (default 200)")
    ap.add_argument("--seats", type=int, default=None,
                    help="total seats in the show (default: auto, ~4 random requests per seat)")
    ap.add_argument("--ramp", type=float, default=3.0, help="seconds to spread out opening connections (default 3)")
    ap.add_argument("--admin-key", default=os.environ.get("ADMIN_API_KEY", "local-dev-admin-key-change-me"))
    a = ap.parse_args()
    base, run = a.base_url.rstrip("/"), str(int(time.time()))

    n_hot = a.requests * 3 // 10
    n_random = a.requests - n_hot
    # Scenario seats: always present, each scenario's checks rely on them.
    named = ["H1", "F1", "B1", "P1", "P2", "P3", "T1", "T2", "K1", "Q1", "Q2", "X1"]
    named += [f"L{i}" for i in range(1, 6)] + [f"G{i}" for i in range(1, 11)] + [f"D{i}" for i in range(1, 5)]

    # --seats only decides how many R* seats the random bookings compete for.
    if a.seats is None:
        n_random_seats = n_random // 4 + 1  # fallback: ~4 people per random seat
    elif not len(named) + 1 <= a.seats <= 10_000:  # 10,000 = the API's max seats per show
        sys.exit(f"--seats must be between {len(named) + 1} ({len(named)} scenario seats + 1) and 10000")
    else:
        n_random_seats = a.seats - len(named)
    random_seats = [f"R{i}" for i in range(1, n_random_seats + 1)]

    # ---- setup -------------------------------------------------------------
    r = request(base, "POST", "/shows",
                {"name": f"burst-{run}", "seats": random_seats + named,
                 "price_paise": 25000, "per_user_limit": LIMIT},
                {"x-admin-key": a.admin_key})
    if r["status"] != 201:
        sys.exit(f"could not create show (check --admin-key): {r['status']} {r['body'] or r.get('error')}")
    sid = r["body"]["id"]

    def token(name):  # a named user, unique per run
        return request(base, "POST", "/auth/token", {"user_id": f"{name}-{run}"})["body"]["token"]

    bulk, need = [], n_random + n_hot + 5
    while len(bulk) < need:
        n = min(10_000, need - len(bulk))
        bulk += [t["token"] for t in request(base, "POST", "/auth/tokens", {"count": n})["body"]]

    def reserve(tok, seats, key, extra=None, request_id=None, ramp=0.0):
        return request(base, "POST", f"/shows/{sid}/reserve",
                       {"seats": seats, "idempotency_key": key, **(extra or {})},
                       {"authorization": f"Bearer {tok}"}, request_id, ramp)

    # Done before the burst (and before the metrics snapshot): seats already
    # taken, a key already used, a user already at the limit.
    owner, keyreuser, limited = token("owner"), token("keyreuser"), token("limited")
    reserve(owner, ["B1"], "pre-b")
    reserve(owner, ["P1"], "pre-p")
    reserve(keyreuser, ["Q1"], "same-key")
    for i in range(1, 5):
        reserve(limited, [f"L{i}"], f"pre-l{i}")

    # ---- the burst: (scenario, token, seats, key, extra body) ---------------
    twice, retrier, greedy, spoofer = token("twice"), token("retrier"), token("greedy"), token("spoofer")
    jobs = [("random", bulk.pop(), [random.choice(random_seats)], "k", None) for _ in range(n_random)]
    jobs += [("hot", bulk.pop(), ["H1"], "k", None) for _ in range(n_hot)]
    jobs += [("fight", bulk.pop(), ["F1"], "k", None) for _ in range(5)]
    jobs += [("already_booked", token(f"late{i}"), ["B1"], "k", None) for i in range(5)]
    jobs += [("bulk_partial", token(f"bulk{i}"), ["P1", f"P{2 + i % 2}"], "k", None) for i in range(6)]
    jobs += [("twice", twice, ["T1"], "t1", None), ("twice", twice, ["T2"], "t2", None)]
    jobs += [("retry", retrier, ["K1"], "same", None) for _ in range(5)]
    jobs += [("key_reuse", keyreuser, ["Q2"], "same-key", None)]
    jobs += [("limit", limited, ["L5"], "l5", None)]
    jobs += [("greedy", greedy, [f"G{i}"], f"g{i}", None) for i in range(1, 11)]
    pairs = [["D1", "D2"], ["D2", "D1"], ["D2", "D3"], ["D3", "D2"], ["D3", "D4"], ["D4", "D1"]]
    jobs += [("deadlock", token(f"dl{i}"), pairs[i % 6], "k", None) for i in range(30)]
    jobs += [("spoof", spoofer, ["X1"], "x", {"user_id": "someone-else"})]
    random.shuffle(jobs)

    before = metrics(base)
    bad_counts = []
    stop = threading.Event()

    def poll():  # counts must add up *during* the burst too
        while not stop.is_set():
            p = request(base, "GET", f"/shows/{sid}")
            if p["status"] == 200:
                c = p["body"]["counts"]
                if c["available"] + c["held"] + c["confirmed"] != c["total_seats"]:
                    bad_counts.append(c)
            time.sleep(0.2)

    def fire(numbered):
        n, (scen, tok, seats, key, extra) = numbered
        t = time.perf_counter()
        res = reserve(tok, seats, key, extra, f"burst{run}-{n}", a.ramp)
        res.update(scenario=scen, seats=seats, elapsed_ms=round((time.perf_counter() - t) * 1000))
        return res

    print(f"show {sid}: {len(random_seats) + len(named)} seats "
          f"({len(random_seats)} random + {len(named)} scenario), limit {LIMIT}")
    print(f"  {n_random} random requests on {len(random_seats)} seats (~{n_random / len(random_seats):.1f} per seat), "
          f"{n_hot} on hot seat H1, {len(jobs) - n_random - n_hot} scenario requests")
    print(f"Firing {len(jobs)} reserves, concurrency {a.concurrency}, ramp {a.ramp}s ...")
    poller = threading.Thread(target=poll)
    poller.start()
    t0 = time.perf_counter()
    with ThreadPoolExecutor(a.concurrency) as pool:
        results = list(pool.map(fire, enumerate(jobs)))
    took = time.perf_counter() - t0
    stop.set()
    poller.join()
    after = metrics(base)

    # ---- outcomes ------------------------------------------------------------
    def err_code(x):
        return x["body"].get("error") if isinstance(x["body"], dict) else None

    def label(x):
        if x["status"] == 0:
            return f"no response ({x['phase']}): {x['error'][:70]}"
        if x["status"] >= 500:
            return f"{x['status']} server error"
        return f"{x['status']} {err_code(x) or 'ok'}"

    answered = [x for x in results if x["status"]]
    lat = sorted(x["elapsed_ms"] for x in answered)
    pct = lambda p: lat[min(len(lat) - 1, int(len(lat) * p))] if lat else 0
    print(f"\ndone in {took:.1f}s ({len(results) / took:.0f} req/s). "
          f"Client latency p50 {pct(.5)} ms, p95 {pct(.95)} ms, p99 {pct(.99)} ms, max {lat[-1] if lat else 0} ms")
    print("Outcomes:")
    for name, n in Counter(label(x) for x in results).most_common():
        print(f"  {n:>6}  {name}")
    resent = [x for x in results if x["resent"]]
    if resent:
        print(f"  ({len(resent)} were resent after a dropped connection; first errors: "
              f"{dict(Counter(x['first_error'].split(':')[0] + ': ' + x['first_error'].split(':')[1].strip() for x in resent).most_common(3))})")

    # ---- failure report: every request that didn't get a normal answer -------
    failures = [x for x in results if x["status"] == 0 or x["status"] >= 500]
    if failures:
        path = f"burst-{run}-failures.jsonl"
        with open(path, "w") as f:
            for x in failures:
                f.write(json.dumps({k: x.get(k) for k in ("request_id", "scenario", "seats", "status", "phase",
                                                          "error", "resent", "first_error", "elapsed_ms", "body")})
                        + "\n")
        print(f"\nFailures ({len(failures)}), all written to {path}:")
        for (status, phase), group in Counter((x["status"], x.get("phase")) for x in failures).items():
            sample = next(x for x in failures if (x["status"], x.get("phase")) == (status, phase))
            why = PHASE_MEANING.get(phase, "server returned an error: look up the request_id in the server logs")
            print(f"  {group:>6} x {'no response' if status == 0 else status} [{phase or 'server'}] - {why}")
            print(f"           e.g. request_id={sample['request_id']} scenario={sample['scenario']} "
                  f"seats={sample['seats']} error={sample.get('error') or str(sample['body'])[:120]}")

    # ---- checks ----------------------------------------------------------------
    # A resent request that got 200 means its first copy booked the seat and
    # that 201 was lost on the way back: it counts as a win.
    def won(x):
        return x["status"] == 201 or (x["status"] == 200 and x["resent"] and x["scenario"] != "retry")

    by = {}
    for x in results:
        by.setdefault(x["scenario"], []).append(x)
    codes = lambda scen: dict(Counter((f"{x['status']}r" if x["resent"] else x["status"]) for x in by[scen]))
    wins = lambda scen: sum(1 for x in by[scen] if won(x))
    lost = lambda scen: sum(1 for x in by[scen] if x["status"] == 0)

    def exactly(scen, n):
        """n winners, or fewer only if the missing ones got no answer at all."""
        return wins(scen) <= n <= wins(scen) + lost(scen)
    answered_codes = lambda scen: {x["status"] for x in by[scen] if x["status"]}
    state = request(base, "GET", f"/shows/{sid}")["body"]
    seat_status = {s["seat_label"]: s["status"] for s in state["seats"]}
    counts = state["counts"]
    unanswered = sum(1 for x in results if x["status"] == 0)
    failed, warned = [], []

    def check(name, ok, detail, warn_only=False):
        tag = "PASS" if ok else ("WARN" if warn_only else "FAIL")
        print(f"  [{tag}] {name}  ({detail})")
        if not ok:
            (warned if warn_only else failed).append(name)

    print("\nChecks:  (codes: 201/409/...; '200r' = answered after a resend; 0 = no response)")
    n5xx = sum(1 for x in results if x["status"] >= 500)
    check("zero 5xx from the server", n5xx == 0, f"{n5xx} x 5xx")
    check("every request got an answer", unanswered == 0,
          f"{unanswered} without response: network/client side, see failures above", warn_only=True)
    won_seats = [s for x in results if x["status"] == 201 for s in x["seats"]]
    dup = [s for s, n in Counter(won_seats).items() if n > 1]
    check("no seat sold twice", not dup, f"{len(won_seats)} seats in 201s, duplicates: {dup or 'none'}")
    check("hot seat H1: exactly one winner", exactly("hot", 1), codes("hot"))
    check("small fight F1: exactly one winner", exactly("fight", 1), codes("fight"))
    check("already-booked B1: every answer is 409", answered_codes("already_booked") <= {409}, codes("already_booked"))
    check("bulk with a taken seat: every answer 409, P2/P3 still free",
          answered_codes("bulk_partial") <= {409} and seat_status["P2"] == seat_status["P3"] == "available",
          f"{codes('bulk_partial')}, P2={seat_status['P2']}, P3={seat_status['P3']}")
    check("one user, two separate bookings: both booked", exactly("twice", 2), codes("twice"))
    ids = {x["body"]["reservation_id"] for x in by["retry"] if x["status"] in (200, 201)}
    check("same request 5x in parallel: one booking", sum(1 for x in by["retry"] if x["status"] == 201) <= 1
          and len(ids) == 1, f"{codes('retry')}, {len(ids)} reservation id(s)")
    check("same key, different seats: 409, Q2 still free",
          answered_codes("key_reuse") <= {409} and seat_status["Q2"] == "available", codes("key_reuse"))
    check("user at limit asks for one more: 409", answered_codes("limit") <= {409}, codes("limit"))
    check(f"10 parallel requests from one user: exactly {LIMIT} booked", exactly("greedy", LIMIT), codes("greedy"))
    check("overlapping multi-seat requests: no 5xx", all(x["status"] < 500 for x in by["deadlock"]), codes("deadlock"))
    spoof = by["spoof"][0]
    spoof_user = spoof["body"].get("user_id", "") if isinstance(spoof["body"], dict) else ""
    check("user_id in body ignored", spoof_user.startswith("spoofer-"), f"booked as {spoof_user!r}")
    check("counts add up during the burst", not bad_counts, f"{len(bad_counts)} bad snapshots")
    check("counts add up after", counts["available"] + counts["held"] + counts["confirmed"] == counts["total_seats"],
          json.dumps(counts))

    # Seats the server confirmed must equal seats we know were won, give or take
    # requests that got no answer at all (they may have been processed).
    pre_booked = 1 + 1 + 1 + 4  # B1, P1, Q1, L1-L4
    lost_201_seats = {s for x in results if won(x) and x["status"] == 200 for s in x["seats"]} - set(won_seats)
    expected = len(won_seats) + len(lost_201_seats) + pre_booked
    check("confirmed seats == seats we saw booked", expected <= counts["confirmed"] <= expected + unanswered,
          f"{counts['confirmed']} confirmed; seen {len(won_seats)} in 201s + {len(lost_201_seats)} via resend "
          f"+ {pre_booked} before" + (f" (+ up to {unanswered} unanswered)" if unanswered else ""))

    if before and after:
        d = lambda m: after.get(m, 0) - before.get(m, 0)
        seen = Counter((x["status"], err_code(x)) for x in results)
        lost_201 = sum(1 for x in results if won(x) and x["status"] == 200)
        # Each resent or unanswered request may have reached the server once
        # more than we saw, so the server may count up to that many extra.
        slack = len(resent) + unanswered
        rows = [("confirmed", d("reservations_confirmed_total"), seen[(201, None)] + lost_201)]
        for reason, err in [("seat_taken", "seats_unavailable"), ("per_user_limit", "per_user_limit_exceeded"),
                            ("idempotency_key_reused", "idempotency_key_reused")]:
            rows.append((reason, d(f'reservations_declined_total{{reason="{reason}"}}'), seen[(409, err)]))
        rows.append(("idempotent_replay", d('reservations_declined_total{reason="idempotent_replay"}'),
                     seen[(200, None)]))
        off = [f"{n}: metrics {m:.0f} vs seen {o}" for n, m, o in rows if not o <= m <= o + slack]
        extra = sum(m - o for _, m, o in rows)
        check("/metrics matches responses", not off and extra <= slack,
              "; ".join(off) or ", ".join(f"{n}={m:.0f}" for n, m, _ in rows)
              + (f" ({extra:.0f} extra server-side from {slack} resent/unanswered)" if extra else ""))
        m5xx = sum(v - before.get(k, 0) for k, v in after.items()
                   if k.startswith("http_requests_total") and re.search(r'status="5', k))
        check("/metrics shows zero 5xx", m5xx == 0, f"{m5xx:.0f}")
    else:
        print("  [SKIP] /metrics not readable")

    verdict = "ALL CHECKS PASSED" if not failed else f"{len(failed)} CHECK(S) FAILED"
    print(f"\n{verdict}" + (f" ({len(warned)} warning(s))" if warned else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
