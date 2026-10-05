#!/usr/bin/env python3
"""
Remediation — Option B: create, run, and monitor a Sigma materialization via the REST API.

Sigma's API can LIST, CREATE, UPDATE, and DELETE materialization schedules, plus TRIGGER
and MONITOR a one-off run. A schedule body is a cron cadence — there is no user-chosen
destination field. Sigma writes a table or dynamic table into its managed write-back
schema in the customer's warehouse.

Schedule create/update/delete use the element-scoped public-beta route
(".../elements/{elementId}/materializationSchedules"). The workbook list endpoint is
currently v2.1 and remains unscoped and hyphenated.
  https://help.sigmacomputing.com/reference/create-materialization-schedule
  https://help.sigmacomputing.com/reference/patch-materialization-schedule
  https://help.sigmacomputing.com/reference/delete-materialization-schedule
  https://help.sigmacomputing.com/reference/create-data-model-materialization-schedule
  https://help.sigmacomputing.com/reference/patch-data-model-materialization-schedule
  https://help.sigmacomputing.com/reference/delete-data-model-materialization-schedule
An element can have at most one schedule, and CREATE starts an immediate run. Use
`--dry-run` to inspect any state-changing request before sending it.

  list:    python3 scripts/materialize.py list   --workbook <workbookId>
           python3 scripts/materialize.py list   --datamodel <dataModelId>
  run:     python3 scripts/materialize.py run    --workbook <workbookId>  --sheet-id <sheetId>
           python3 scripts/materialize.py run    --datamodel <dataModelId> --sheet-id <sheetId>
  create:  python3 scripts/materialize.py create --workbook <workbookId>  --element-id <elementId> --cron "0 0 * * *" [--timezone America/New_York]
           python3 scripts/materialize.py create --datamodel <dataModelId> --element-id <elementId> --cron "0 0 * * *"
  update:  same flags as create, against an existing schedule
  delete:  python3 scripts/materialize.py delete --workbook <workbookId>  --element-id <elementId> [--yes]
           python3 scripts/materialize.py delete --datamodel <dataModelId> --element-id <elementId> [--yes]
           # delete is destructive (cancels all future runs, no undo) — prompts for
           # confirmation unless --yes is passed.

Auth: reads SIGMA_API_TOKEN + SIGMA_BASE_URL from the environment
(e.g. eval "$(~/.claude/skills/tableau-to-sigma/scripts/get-token.sh)").
"""
import argparse, json, os, sys, time, urllib.request, urllib.parse, urllib.error

BASE = os.environ.get("SIGMA_BASE_URL", "").rstrip("/")
TOKEN = os.environ.get("SIGMA_API_TOKEN", "")


def authenticate():
    global TOKEN
    if TOKEN:
        return
    client_id = os.environ.get("SIGMA_CLIENT_ID")
    client_secret = os.environ.get("SIGMA_CLIENT_SECRET")
    if not BASE or not client_id or not client_secret:
        sys.exit("Set SIGMA_BASE_URL and either SIGMA_API_TOKEN or "
                 "SIGMA_CLIENT_ID + SIGMA_CLIENT_SECRET.")
    form = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }).encode()
    req = urllib.request.Request(
        f"{BASE}/v2/auth/token", data=form, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            TOKEN = json.load(response)["access_token"]
    except urllib.error.HTTPError as exc:
        sys.exit(f"Sigma auth -> HTTP {exc.code}: "
                 f"{exc.read().decode(errors='replace')[:300]}")


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
        path = f"/v2.1/workbooks/{args.workbook}/materialization-schedules"
    else:
        path = f"/v2/dataModels/{args.datamodel}/materializationSchedules"
    ents, page = [], None
    while True:
        params = {"limit": 200} if args.workbook else {"pageSize": 200}
        if page:
            params["page" if args.workbook else "pageToken"] = page
        d = api("GET", path + "?" + urllib.parse.urlencode(params))
        ents.extend(d.get("entries", []))
        page = d.get("nextPage") or d.get("nextPageToken")
        if not page:
            break
    print(f"{len(ents)} materialization schedule(s):")
    for e in ents:
        sch = e.get("schedule") or {}
        print(f"  sheetId={e.get('sheetId')}  elementId={e.get('elementId')}  "
              f"element={e.get('elementName')!r}  "
              f"cron={sch.get('cronSpec')}  tz={sch.get('timezone')}  paused={e.get('paused')}")
    if not ents:
        print("  (none — create one with `materialize.py create --element-id <elementId> --cron "
              "\"<cron>\"` (public beta REST) or via the Sigma UI: element ⋮ → Materialization)")
    return ents


def _schedule_path(args):
    """Element-scoped materializationSchedules path (create/update/delete), NOT the
    same as list_schedules' unscoped workbook/data-model
    path above."""
    if args.workbook:
        return (f"/v2/workbooks/{args.workbook}/elements/"
                f"{args.element_id}/materializationSchedules")
    return (f"/v2/dataModels/{args.datamodel}/elements/"
            f"{args.element_id}/materializationSchedules")


def _schedule_body(args):
    schedule = {"cronSpec": args.cron}
    if args.timezone:
        schedule["timezone"] = args.timezone
    return {"schedule": schedule}


def create_schedule(args):
    if args.dry_run:
        return print(json.dumps({"dryRun": True, "method": "POST",
                                 "path": _schedule_path(args),
                                 "body": _schedule_body(args)}, indent=2))
    d = api("POST", _schedule_path(args), _schedule_body(args))
    print(json.dumps(d, indent=2))


def update_schedule(args):
    if args.dry_run:
        return print(json.dumps({"dryRun": True, "method": "PATCH",
                                 "path": _schedule_path(args),
                                 "body": _schedule_body(args)}, indent=2))
    d = api("PATCH", _schedule_path(args), _schedule_body(args))
    print(json.dumps(d, indent=2))


def delete_schedule(args):
    target = args.workbook or args.datamodel
    kind = "workbook" if args.workbook else "datamodel"
    if args.dry_run:
        return print(json.dumps({"dryRun": True, "method": "DELETE",
                                 "path": _schedule_path(args)}, indent=2))
    if not args.yes:
        resp = input(f"Delete the materialization schedule for {kind}={target} "
                     f"element={args.element_id}? This cancels all future scheduled runs and "
                     f"cannot be undone. Type 'yes' to confirm: ")
        if resp.strip().lower() != "yes":
            sys.exit("Aborted (pass --yes to skip this prompt).")
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
        if st in ("failed", "error", "cancelled", "canceled"):
            return j, False
        time.sleep(5)
    return {}, False


def run(args):
    if args.workbook:
        post_path = f"/v2/workbooks/{args.workbook}/materializations"
        get_path = f"/v2/workbooks/{args.workbook}/materializations"
    else:
        post_path = f"/v2/dataModels/{args.datamodel}:materialize"
        get_path = f"/v2/dataModels/{args.datamodel}/materializations"
    body = {"sheetId": args.sheet_id}
    if args.dry_run:
        return print(json.dumps({"dryRun": True, "method": "POST",
                                 "path": post_path, "body": body}, indent=2))
    res = api("POST", post_path, body)
    mid = res.get("materializationId")
    if not mid:
        sys.exit(f"Trigger returned no materializationId: {json.dumps(res)[:300]}")
    job, ok = poll(get_path, mid)
    print(json.dumps({"materializationId": mid, "ok": ok, "job": job}, indent=2))
    sys.exit(0 if ok else 1)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("list", "run", "create", "update", "delete"):
        s = sub.add_parser(name)
        s.add_argument("--workbook")
        s.add_argument("--datamodel")
        if name == "run":
            s.add_argument("--sheet-id", help="sheetId returned by `list`")
            s.add_argument("--sheet", help=argparse.SUPPRESS)
        elif name in ("create", "update", "delete"):
            s.add_argument("--element-id", help="elementId returned by `list`/elements API")
            s.add_argument("--sheet", help=argparse.SUPPRESS)
        if name in ("run", "create", "update", "delete"):
            s.add_argument("--dry-run", action="store_true",
                           help="print the state-changing request without sending it")
        if name in ("create", "update"):
            s.add_argument("--cron", required=True, help='cron expression, e.g. "0 0 * * *"')
            s.add_argument("--timezone", help="IANA timezone, e.g. America/New_York (optional)")
        if name == "delete":
            s.add_argument("--yes", "-y", action="store_true",
                            help="skip the delete confirmation prompt (for scripting)")
    a = ap.parse_args()
    if not (a.workbook or a.datamodel):
        sys.exit("pass --workbook <id> or --datamodel <id>")
    if a.workbook and a.datamodel:
        sys.exit("pass exactly one of --workbook or --datamodel")
    if a.cmd == "run":
        a.sheet_id = a.sheet_id or a.sheet
        if not a.sheet_id:
            sys.exit("run requires --sheet-id <sheetId>")
    elif a.cmd in ("create", "update", "delete"):
        a.element_id = a.element_id or a.sheet
        if not a.element_id:
            sys.exit(f"{a.cmd} requires --element-id <elementId>")
    if not getattr(a, "dry_run", False):
        if not BASE:
            sys.exit("Set SIGMA_BASE_URL.")
        authenticate()
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
