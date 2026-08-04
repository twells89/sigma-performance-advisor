#!/usr/bin/env python3
"""
Remediation — Option B: create, run, and monitor a Sigma materialization via the REST API.

Sigma's API can LIST, CREATE, UPDATE, and DELETE materialization schedules, plus TRIGGER
and MONITOR a one-off run. A schedule body is just a cron cadence — there is no
destination/target field; materialization always writes back to Sigma's own internal
cache, not a user-chosen table. (Earlier revisions of this script and the playbook
claimed schedule creation was UI-only with no REST endpoint — that was false, retracted
2026-08; see refs/materialization-playbook.md for the full writeup.)

Private-beta / live-deployment caveat: create/update/delete hit a newer, element-scoped
route (".../elements/{elementId}/materializationSchedules") whose path and body shape
are confirmed correct against Sigma's own help-center reference pages (which label this
"a private beta feature"), but the route was NOT reachable (404 "UnmatchedHandler", on
every verb including GET) against a live test org as of 2026-08-04 — confirmed via
real-vs-fake-ID and working-sibling-endpoint controls, not assumed; a rollout gap on that
org, not a wrong shape. `list` and `run` (pre-existing, unchanged below) are unaffected
and already live-verified working. Re-test create/update/delete before depending on them
for a given org.

  list:    python3 scripts/materialize.py list   --workbook <workbookId>
           python3 scripts/materialize.py list   --datamodel <dataModelId>
  run:     python3 scripts/materialize.py run    --workbook <workbookId>  --sheet <elementId>
           python3 scripts/materialize.py run    --datamodel <dataModelId> --sheet <elementId>
  create:  python3 scripts/materialize.py create --workbook <workbookId>  --sheet <elementId> --cron "0 0 * * *" [--timezone America/New_York]
           python3 scripts/materialize.py create --datamodel <dataModelId> --sheet <elementId> --cron "0 0 * * *"
  update:  same flags as create, against an existing schedule
  delete:  python3 scripts/materialize.py delete --workbook <workbookId>  --sheet <elementId>
           python3 scripts/materialize.py delete --datamodel <dataModelId> --sheet <elementId>

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


def _schedule_path(args):
    """Element-scoped materializationSchedules path (create/update/delete) — new Beta
    route, NOT the same as list_schedules' unscoped workbook/data-model path above."""
    if args.workbook:
        return f"/v2/workbooks/{args.workbook}/elements/{args.sheet}/materializationSchedules"
    return f"/v2/dataModels/{args.datamodel}/elements/{args.sheet}/materializationSchedules"


def _schedule_body(args):
    schedule = {"cronSpec": args.cron}
    if args.timezone:
        schedule["timezone"] = args.timezone
    return {"schedule": schedule}


def create_schedule(args):
    d = api("POST", _schedule_path(args), _schedule_body(args))
    print(json.dumps(d, indent=2))


def update_schedule(args):
    d = api("PATCH", _schedule_path(args), _schedule_body(args))
    print(json.dumps(d, indent=2))


def delete_schedule(args):
    d = api("DELETE", _schedule_path(args))
    print(json.dumps(d, indent=2) if d else "deleted")


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
    for name in ("list", "run", "create", "update", "delete"):
        s = sub.add_parser(name)
        s.add_argument("--workbook")
        s.add_argument("--datamodel")
        if name in ("run", "create", "update", "delete"):
            s.add_argument("--sheet", required=True, help="elementId (sheetId from `list`)")
        if name in ("create", "update"):
            s.add_argument("--cron", required=True, help='cron expression, e.g. "0 0 * * *"')
            s.add_argument("--timezone", help="IANA timezone, e.g. America/New_York (optional)")
    a = ap.parse_args()
    if not (a.workbook or a.datamodel):
        sys.exit("pass --workbook <id> or --datamodel <id>")
    dispatch = {
        "list": list_schedules,
        "run": run,
        "create": create_schedule,
        "update": update_schedule,
        "delete": delete_schedule,
    }
    dispatch[a.cmd](a)


if __name__ == "__main__":
    main()
