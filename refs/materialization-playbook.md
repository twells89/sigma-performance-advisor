# Sigma materialization API supplement

For decision policy, ROI, controls, and removal safeguards, read
[`performance-cost-playbook.md`](performance-cost-playbook.md).

## Behavior

Sigma writes materialized workbook/data-model elements to a Sigma-managed write-back
schema in the customer's warehouse as tables or, where supported, dynamic tables.
There is no user-selected destination in the schedule API.

- Workbook schedule list:
  `GET /v2.1/workbooks/{workbookId}/materialization-schedules`
- Workbook create/update/delete:
  `POST|PATCH|DELETE
  /v2/workbooks/{workbookId}/elements/{elementId}/materializationSchedules`
- Workbook on-demand refresh:
  `POST /v2/workbooks/{workbookId}/materializations {"sheetId":"..."}`
- Data-model schedule list:
  `GET /v2/dataModels/{dataModelId}/materializationSchedules`
- Data-model create/update/delete:
  `POST|PATCH|DELETE
  /v2/dataModels/{dataModelId}/elements/{elementId}/materializationSchedules`
- Data-model on-demand refresh:
  `POST /v2/dataModels/{dataModelId}:materialize {"sheetId":"..."}`

Schedule creation is currently documented as public beta and starts an immediate run.
An element can have at most one schedule. Create/update bodies are:

```json
{"schedule":{"cronSpec":"0 0 * * *","timezone":"America/New_York"}}
```

## Safety

- `materialize.py list` is read-only.
- Use `--dry-run` before `create`, `update`, `delete`, or `run`.
- `delete` cancels future runs and has no undo; preserve cron/timezone and require owner
  approval.
- A direct control target can bypass materialization. Current APIs do not expose complete
  control target bindings, so control-bearing workbooks require manual review.
- Materialization ownership and connection credentials affect refresh behavior.

Official references:
- https://help.sigmacomputing.com/docs/materialization
- https://help.sigmacomputing.com/reference/create-materialization-schedule
- https://help.sigmacomputing.com/reference/patch-materialization-schedule
- https://help.sigmacomputing.com/reference/delete-materialization-schedule
- https://help.sigmacomputing.com/reference/materialize-workbook-element
