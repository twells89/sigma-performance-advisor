#!/usr/bin/env python3
"""
Remediation — Option B: run/refresh a Sigma materialization via the REST API.

Sigma's API can TRIGGER and MONITOR a materialization, and LIST existing schedules.
It cannot CREATE a schedule — that one-time setup (pick element + destination + cadence)
is done in the Sigma UI (Element menu → Materialization). Once a schedule exists, this
script refreshes it on demand and polls the job to completion.

  list:     python3 scripts/materialize.py list --workbook <workbookId>
  run:      python3 scripts/materialize.py run  --workbook <workbookId> --sheet <sheetId>
            python3 scripts/materialize.py run  --datamodel <dataModelId> --sheet <sheetId>

Auth: reads SIGMA_API_TOKEN + SIGMA_BASE_URL from the environment
(e.g. eval "$(~/.claude/skills/tableau-to-sigma/scripts/get-token.sh)").
"""
import argparse, json, os, sys, time, urllib.request, urllib.parse, urllib.error

BASE = os.environ.get("SIGMA_BASE_URL", "").rstrip("/")
TOKEN = os.environ.get("SIGMA_API_TOKEN", "")


def api(method, path, body=None):
    url = f"{BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Authorization": f"Bearer {TOKEN}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            t = r.read().decode()
            return json.loads(t) if t.strip() else {}
    except urllib.error.HTTPError as e:
        sys.exit(f"{method} {path} -> HTTP {e.code}: {e.read().decode()[:300]}")


def list_schedules(args):
    if args.workbook:
        d = api("GET", f"/v2/workbooks/{args.workbook}/materialization-schedules?limit=200")
    else:
        d = api("GET", f"/v2/dataModels/{args.datamodel}/materializationSchedules?limit=200")
    ents = d.get("entries", [])
    print(f"{len(ents)} materialization schedule(s):")
    for e in ents:
        sch = e.get("schedule") or {}
        print(f"  sheetId={e.get('sheetId')}  element={e.get('elementName')!r}  "
              f"cron={sch.get('cronSpec')}  tz={sch.get('timezone')}  paused={e.get('paused')}")
    if not ents:
        print("  (none — create one in the Sigma UI: open the element → ⋮ → Materialization)")
    return ents


def poll(get_path, job_id, timeout=300):
    print(f"  triggered materializationId={job_id} — polling...", file=sys.stderr)
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = api("GET", f"{get_path}/{job_id}")
        st = (j.get("status") or j.get("state") or "").lower()
        print(f"    [{int(time.time()-t0)}s] status={st or j}", file=sys.stderr)
        if st in ("completed", "success", "succeeded", "ready", "done"):
            return j, True
        if st in ("failed", "error", "cancelled"):
            return j, False
        time.sleep(5)
    return {}, False


def run(args):
    if args.workbook:
        res = api("POST", f"/v2/workbooks/{args.workbook}/materializations",
                  {"sheetId": args.sheet})
        mid = res.get("materializationId")
        job, ok = poll(f"/v2/workbooks/{args.workbook}/materializations", mid)
    else:
        res = api("POST", f"/v2/dataModels/{args.datamodel}:materialize",
                  {"sheetId": args.sheet})
        mid = res.get("materializationId")
        job, ok = poll(f"/v2/dataModels/{args.datamodel}/materializations", mid)
    print(json.dumps({"materializationId": mid, "ok": ok, "job": job}, indent=2))
    sys.exit(0 if ok else 1)


def main():
    if not BASE or not TOKEN:
        sys.exit('Set creds: eval "$(~/.claude/skills/tableau-to-sigma/scripts/get-token.sh)"')
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("list", "run"):
        s = sub.add_parser(name)
        s.add_argument("--workbook")
        s.add_argument("--datamodel")
        if name == "run":
            s.add_argument("--sheet", required=True, help="sheetId from `list`")
    a = ap.parse_args()
    if not (a.workbook or a.datamodel):
        sys.exit("pass --workbook <id> or --datamodel <id>")
    (list_schedules if a.cmd == "list" else run)(a)


if __name__ == "__main__":
    main()
