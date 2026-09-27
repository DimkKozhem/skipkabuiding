import assert from "node:assert/strict";
import test from "node:test";
import { equipmentInventory, groupAlertsForQueue, humanToken, isEarlierSlice, ksgPlanPhrase, noteAuthorLabel, planFactCaption, planFactFromAlert, planFactFromZone, publicText, siteChangeLines, sortAttentionAlerts, statusLabel, statusTone, subjectFromExpected, typeLabel, zoneUiStatus } from "../src/labels.ts";

test("missing equipment observation stays unknown, while an observed zero stays zero", () => {
  const absent = planFactFromAlert("missing_equipment", { dump_truck: 2 }, {});
  assert.equal(absent[0].observed, "—");
  assert.equal(absent[0].observedValue, null);
  assert.equal(absent[0].mismatch, false);
  const observed = planFactFromAlert("missing_equipment", { dump_truck: 2 }, { dump_truck: 0 });
  assert.equal(observed[0].observedValue, 0);
  assert.equal(observed[0].mismatch, true);
});

test("a zone without an observation cannot appear healthy or report zero equipment", () => {
  const rows = planFactFromZone({ required_equipment: [{ type: "dump_truck", min_count: 2 }] }, null);
  assert.equal(rows[0].observed, "—");
  assert.equal(rows[0].mismatch, false);
  assert.equal(zoneUiStatus({ open_alerts: 0, last_actual: null }), "insufficient");
});

test("a zero-confidence slab count is not presented as a floor fact", () => {
  const [row] = planFactFromZone(
    { expected: { floors: 6, slabs: 0 } },
    {
      elements: {
        floors: { count: 0, max_confidence: 0 },
        slabs: { count: 23, max_confidence: 0 },
      },
      scene_attributes: { structural_levels: 23, visible_floor_levels: 23 },
    },
  );
  assert.equal(row.key, "floors");
  assert.equal(row.expectedValue, 6);
  assert.equal(row.observedValue, null);
  assert.equal(row.observed, "Не определено");
  assert.equal(row.mismatch, false);
});

test("divider length is the plan line when the schedule is not about floors", () => {
  const [row] = planFactFromZone({ expected: { dividing_line_m: 18 } }, null);
  assert.equal(row.key, "dividing_line_m");
  assert.equal(row.expected, "18 м");
  assert.equal(row.observed, "—");
});

test("plan and fact preserve numeric values for a real zero and building comparison", () => {
  const rows = planFactFromZone({ expected: { floors: 6 } }, { scene_attributes: { structural_levels: 4 } });
  assert.equal(rows[0].expectedValue, 6);
  assert.equal(rows[0].observedValue, 4);
  assert.equal(rows[0].mismatch, true);
  const zero = planFactFromAlert("schedule_delay", { floors: 4 }, { floors: 0 });
  assert.equal(zero[0].observedValue, 0);
});

const alert = (id, zone, date, severity = "warning", type = "schedule_delay") => ({ id, zone, severity, type, related_dates: [date] });
test("priority uses API severity and latest slices, independently of demo zone names", () => {
  const rows = [alert("old", "tower-west", "2026-09-01"), alert("current", "tower-west", "2026-09-22"), alert("equipment", "pit", "2026-09-18", "warning", "missing_equipment"), alert("critical", "other-site", "2026-08-01", "critical")];
  assert.deepEqual(sortAttentionAlerts(rows).map(row => row.id), ["critical", "current", "equipment", "old"]);
  assert.equal(rows[0].id, "old");
  assert.equal(isEarlierSlice(rows[0], rows), true);
  const proposal = alert("proposal", "tower-west", "2026-12-24", "info", "model_candidate");
  assert.deepEqual(sortAttentionAlerts([...rows, proposal]).map(row => row.id), ["critical", "current", "equipment", "old", "proposal"]);
  assert.equal(typeLabel("model_candidate"), "Предложение модели на проверку");
  assert.deepEqual(planFactFromAlert("model_candidate", { role: "shadow_candidate" }, { detections: [] }), []);
  assert.equal(zoneUiStatus({ open_alerts: 0, alert_counts: { model_candidate: 1 }, last_actual: {} }), "normal");
  assert.equal(zoneUiStatus({ open_alerts: 0, alert_counts: { insufficient_evidence: 2, model_candidate: 1 }, last_actual: {} }), "insufficient");
});

test("equipment inventory and site change stay factual", () => {
  const actual = { equipment: { excavator: { count: 1 }, dump_truck: { count: 2 }, roller: { count: 0 } } };
  assert.deepEqual(equipmentInventory(actual).map(item => [item.key, item.count]), [["dump_truck", 2], ["excavator", 1]]);
  const stable = siteChangeLines({ kind: "unchanged", comparable: true, same_camera: true, equipment_deltas: {}, element_deltas: {} }, actual);
  assert.match(stable[0], /не изменилось/);
  assert.match(stable[1], /конструктива/);
  const moved = siteChangeLines({
    kind: "unchanged",
    comparable: true,
    same_camera: true,
    equipment_deltas: { dump_truck: -1 },
    element_deltas: { floors: 1 },
  }, { ...actual, elements: { floors: { count: 5 } } });
  assert.match(moved[0], /самосвал −1 \(3 → 2\)/);
  assert.match(moved[1], /этажи \+1 \(4 → 5\)/);
  assert.equal(siteChangeLines(null).length, 1);
});

test("minimum equipment count is satisfied when the observed count is higher", () => {
  const [row] = planFactFromAlert("missing_equipment", { dump_truck: 2 }, { dump_truck: 3 });
  assert.equal(row.mismatch, false);
});

test("queue groups current slices and hides earlier dates of the same object", () => {
  const rows = [
    alert("now", "tower-west", "2026-09-22"),
    alert("old", "tower-west", "2026-09-01"),
    alert("pit", "pit", "2026-09-18", "warning", "missing_equipment"),
  ];
  const groups = groupAlertsForQueue(rows);
  assert.equal(groups[0].zone, "tower-west");
  assert.deepEqual(groups[0].current.map(row => row.id), ["now"]);
  assert.deepEqual(groups[0].earlier.map(row => row.id), ["old"]);
  assert.equal(groups[1].zone, "pit");
});

test("road divider schedule phrase shows planned length in meters", () => {
  assert.equal(
    ksgPlanPhrase({ dividing_line_m: 18 }),
    "Разделительная линия 18 м",
  );
});

test("excavation KSG phrase uses equipment, not a zero floor count", () => {
  assert.equal(
    ksgPlanPhrase({ expected: { floors: 0 }, required_equipment: [{ type: "excavator", min_count: 1 }] }),
    "≥ 1 экскаватор",
  );
});

test("internal indicator codes stay out of the inspector text", () => {
  const rows = planFactFromAlert("insufficient_evidence", {
    indicator_id: "foundation_visible",
    foundation: true,
    confirms: "видимый признак фундамента",
  }, { foundation: null, indicator_id: null });
  assert.equal(rows.some(row => String(row.expected).includes("foundation_visible")), false);
  assert.equal(rows.some(row => String(row.observed).includes("foundation_visible")), false);
  assert.equal(subjectFromExpected({ indicator_id: "windows_visible" }), "Окна");
  assert.equal(humanToken("roof_visible"), "Кровля");
  assert.equal(humanToken("not_a_known_code"), "Показатель");
  assert.equal(noteAuthorLabel("sitewatch"), "Система");
  assert.equal(publicText("Москва, сценарий housing_16"), "Москва");
  assert.equal(publicText("Камера таймлапса housing_16"), "Камера таймлапса");
});

test("different check subjects stay separate and presence reads without a raw code", () => {
  const foundation = { id: "a", zone: "office", type: "insufficient_evidence", related_dates: ["2023-01-29"], expected: { indicator_id: "foundation_visible" } };
  const windows = { id: "b", zone: "office", type: "insufficient_evidence", related_dates: ["2023-01-20"], expected: { indicator_id: "windows_visible" } };
  assert.equal(isEarlierSlice(windows, [foundation, windows]), false);
  const older = { id: "c", zone: "office", type: "insufficient_evidence", related_dates: ["2023-01-01"], expected: { indicator_id: "foundation_visible" } };
  assert.equal(isEarlierSlice(older, [foundation, older]), true);
  const [row] = planFactFromAlert("insufficient_evidence", { indicator_id: "foundation_visible", foundation: true }, { foundation: null });
  assert.equal(planFactCaption(row, "plan"), "Ожидается признак: Фундамент");
  assert.equal(planFactCaption(row, "fact"), "Не определено");
  assert.equal(String(row.expected).includes("foundation"), false);
});

test("unknown statuses stay neutral and readable while API labels are preserved", () => {
  assert.equal(statusLabel("future_status", "future_status"), "Требуется проверка");
  assert.equal(statusTone("future_status"), "muted");
  assert.equal(statusLabel("future_status", "Передан на проверку"), "Передан на проверку");
  assert.equal(statusLabel("confirmed"), "Подтверждено");
});
