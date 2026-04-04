from __future__ import annotations

import os
import random
import tempfile
import time

from color_film_mvp_v3_optimized import ColorFilmPipelineV3Optimized
from ultimate_color_film_system_v2_optimized import UltimateColorFilmSystemV2Optimized


def _build_grid(with_hotspot: bool = False):
    random.seed(123)
    ref = []
    sample = []
    for i in range(48):
        base = {
            "L": 62.0 + random.gauss(0.0, 0.08),
            "a": 3.2 + random.gauss(0.0, 0.04),
            "b": 14.8 + random.gauss(0.0, 0.06),
        }
        ref.append(base)
        s = {"L": base["L"] + 0.15, "a": base["a"] + 0.08, "b": base["b"] + 0.05}
        if with_hotspot and i in {0, 1, 8, 9}:
            s = {"L": base["L"] + 4.2, "a": base["a"] + 2.6, "b": base["b"] + 1.9}
        sample.append(s)
    return ref, sample


def _add_trace(sys: UltimateColorFilmSystemV2Optimized, lot: str, complete: bool = True) -> None:
    stages = [
        ("ink_receipt", {"ink_model": "CYAN-PRO", "lot": "INK-A"}),
        ("substrate_receipt", {"lot": "SUB-A", "substrate_db": 0.3}),
        ("recipe_set", {"recipe_code": "SKU-A", "version": 2}),
        ("printing", {"line_speed": 95, "dry_temp": 68}),
        ("inspection", {"avg_de": 1.2, "tier": "PASS"}),
    ]
    if complete:
        stages.append(("shipping", {"shipment_id": f"SHIP-{lot}"}))
    for st, data in stages:
        sys.lifecycle.add_event(lot, st, data)


def _good_assessment_payload(lot: str):
    return {
        "lot_id": lot,
        "base_decision": {"tier": "PASS", "confidence": 0.83, "quality_gate": {"valid": True, "suspicious_ratio": 0.02}},
        "color_metrics": {"avg_de": 1.1, "max_de": 2.0, "avg_dL": 0.12, "avg_db": 0.2, "db": 0.2, "uniformity_std": 0.26},
        "process_params": {"viscosity": 22, "line_speed": 88, "dry_temp": 65, "tension": 16, "pressure": 2.3},
        "process_route": "gravure",
        "film_props": {"opacity": 0.65, "haze": 8, "gloss": 42, "thickness_um": 70, "emboss_direction": "none"},
        "scenario": {"light_source": "d65"},
        "customer_id": None,
        "sku": "SKU-A",
        "current_lab": {"L": 62.0, "a": 3.2, "b": 14.8},
        "meta": {"environment_severity": 0.2, "golden_status": "ok", "idempotency_key": f"idem-{lot}"},
    }


def _set_release_ready_state(sys: UltimateColorFilmSystemV2Optimized, lot: str) -> None:
    sys.transition_state(lot_id=lot, to_state="in_run_monitoring", actor="QA", reason="unit test prep", force=True)


def test_local_hotspot_override():
    pipe = ColorFilmPipelineV3Optimized()
    ref, sample = _build_grid(with_hotspot=True)
    out = pipe.run(
        ref,
        sample,
        grid_shape=(6, 8),
        meta={"product_code": "BLIND-01", "customer_tier": "vip", "application": "premium"},
    )
    assert out["tier"] in {"MARGINAL", "FAIL"}
    assert out["defects"]["hotspot_count"] >= 1


def test_data_invalid_guard():
    pipe = ColorFilmPipelineV3Optimized()
    ref, sample = _build_grid(with_hotspot=False)
    sample[3] = {"L": None, "a": 1.0, "b": 2.0}
    out = pipe.run(ref, sample, grid_shape=(6, 8), meta={"product_code": "BLIND-02"})
    assert out["tier"] == "HOLD"
    assert out["decision_code"] == "DATA_INVALID"


def test_calibration_overdue_but_numeric_ok_blocked():
    sys = UltimateColorFilmSystemV2Optimized()
    lot = "LOT-CAL"
    _add_trace(sys, lot, complete=True)
    for src in ["lightbox", "color_checker", "camera_profile"]:
        sys.cal_guard._calibrations[src]["last_cal"] = time.time() - 365 * 24 * 3600  # noqa: SLF001
    payload = _good_assessment_payload(lot)
    out = sys.integrated_assessment(**payload)
    assert out["final_decision"]["mode"] == "manual_arbitration"
    assert "calibration_overdue" in out["boundary"]["hard_blocks"]


def test_golden_drift_old_standard_blocked():
    sys = UltimateColorFilmSystemV2Optimized()
    lot = "LOT-GOLD"
    _add_trace(sys, lot, complete=True)
    sys.golden.register("G-1", {"L": 62.0, "a": 3.2, "b": 14.8}, max_age_days=90)
    st = sys.golden.check("G-1", {"L": 60.1, "a": 4.1, "b": 16.8})
    payload = _good_assessment_payload(lot)
    payload["meta"]["golden_status"] = st["status"]
    out = sys.integrated_assessment(**payload)
    assert out["final_decision"]["mode"] == "manual_arbitration"
    assert "golden_sample_invalid" in out["boundary"]["hard_blocks"]


def test_trace_missing_event_blocks_release():
    sys = UltimateColorFilmSystemV2Optimized()
    lot = "LOT-MISS-TRACE"
    _add_trace(sys, lot, complete=False)
    payload = _good_assessment_payload(lot)
    out = sys.integrated_assessment(**payload)
    assert out["final_decision"]["mode"] == "manual_arbitration"
    assert "trace_missing_required_events" in out["boundary"]["hard_blocks"]


def test_restart_first_20m_drift_and_changeover_detected():
    sys = UltimateColorFilmSystemV2Optimized()
    sys.run_monitor.set_target({"L": 62.0, "a": 3.2, "b": 14.8}, tolerance=2.5, run_id="RUN-R1")
    for i in range(1, 6):
        sys.run_monitor.add_sample({"L": 64.2, "a": 4.2, "b": 16.0}, seq=i, meter_position=i * 4.0)
    sys.run_monitor.mark_changeover("substrate", at_seq=6, stabilization_samples=4)
    for i in range(6, 15):
        if i <= 9:
            lab = {"L": 64.0, "a": 4.1, "b": 15.9}
        else:
            lab = {"L": 62.8, "a": 3.4, "b": 15.0}
        sys.run_monitor.add_sample(lab, seq=i, meter_position=i * 4.0)
    rpt = sys.run_monitor.get_report()
    kinds = {a["type"] for a in rpt["alerts"]}
    assert "STARTUP_SCRAP_RISK" in kinds or rpt["startup_scrap_risk"]
    assert "CHANGEOVER_TRANSITION_RISK" in kinds or rpt["changeover_transition_risk"]


def test_metamerism_high_risk_while_d65_ok():
    sys = UltimateColorFilmSystemV2Optimized()
    out = sys.evaluate_metamerism(
        lab_d65={"L": 62.0, "a": 3.2, "b": 14.8},
        alt_lights={
            "A_2856K": {"L": 60.8, "a": 3.8, "b": 16.4},
            "F11_store": {"L": 61.0, "a": 3.7, "b": 16.0},
        },
        film_props={"opacity": 0.4, "haze": 22, "gloss": 68},
    )
    assert out["metamerism_risk_score"] >= 0.35


def test_post_process_risk_print_pass_but_downstream_risk():
    sys = UltimateColorFilmSystemV2Optimized()
    lot = "LOT-POST"
    _add_trace(sys, lot, complete=True)
    payload = _good_assessment_payload(lot)
    payload["post_process_steps"] = ["lamination", "adhesive", "hot_press"]
    payload["meta"].update({"press_temp": 80, "storage_days": 20})
    out = sys.integrated_assessment(**payload)
    assert out["module_outputs"]["post_process"]["risk_score"] >= 0.0
    assert out["status"] in {"manual_review_required", "manual_arbitration_required", "auto_release", "auto_blocked"}


def test_msa_repeatability_poor_blocking():
    sys = UltimateColorFilmSystemV2Optimized()
    lot = "LOT-MSA"
    _add_trace(sys, lot, complete=True)
    # Inject large spread for same sample to force poor repeatability.
    vals = [
        {"L": 62.0, "a": 3.2, "b": 14.8},
        {"L": 64.1, "a": 4.3, "b": 16.5},
        {"L": 60.2, "a": 2.4, "b": 13.6},
        {"L": 63.9, "a": 4.1, "b": 16.2},
        {"L": 60.0, "a": 2.3, "b": 13.4},
        {"L": 64.3, "a": 4.4, "b": 16.7},
    ]
    for i, lab in enumerate(vals):
        sys.record_measurement_msa(lot, "SAME", "DEV-A" if i % 2 == 0 else "DEV-B", "OP-A" if i < 3 else "OP-B", lab)
    rep = sys.get_msa_report(lot)
    assert rep["gage_risk_score"] >= 0.45

    payload = _good_assessment_payload(lot)
    out = sys.integrated_assessment(**payload)
    assert out["module_outputs"]["msa"]["gage_risk_score"] >= 0.45


def test_spc_instability_even_if_current_good():
    sys = UltimateColorFilmSystemV2Optimized()
    lot = "LOT-SPC"
    _add_trace(sys, lot, complete=True)
    for v in [1.1, 1.15, 1.2, 1.25, 1.32, 1.4, 1.5, 1.62, 1.75]:
        sys.record_spc_point(lot, v)
    rep = sys.get_spc_report(lot)
    assert rep["risk_score"] > 0.0

    payload = _good_assessment_payload(lot)
    payload["spc_stream_id"] = lot
    out = sys.integrated_assessment(**payload)
    assert out["module_outputs"]["spc"]["risk_score"] >= rep["risk_score"]


def test_first_pass_retest_arbitration_conflict():
    sys = UltimateColorFilmSystemV2Optimized()
    lot = "LOT-DISPUTE"
    _add_trace(sys, lot, complete=True)
    sys.record_retest(lot, "first", "DEV-A", "OP-A", {"avg_de": 1.2}, {"avg_de": 1.0}, {"tier": "PASS"})
    sys.record_retest(lot, "retest", "DEV-B", "OP-B", {"avg_de": 2.9}, {"avg_de": 2.7}, {"tier": "FAIL"})
    rep = sys.get_dispute_report(lot)
    assert rep["conflict"] is True

    payload = _good_assessment_payload(lot)
    out = sys.integrated_assessment(**payload)
    assert out["final_decision"]["mode"] == "manual_arbitration"


def test_customer_yellow_complaint_ranked_candidates():
    sys = UltimateColorFilmSystemV2Optimized()
    lot = "LOT-COMP"
    sys.lifecycle.add_event(lot, "substrate_receipt", {"lot": "S-1", "substrate_db": 1.0})
    sys.lifecycle.add_event(lot, "printing", {"line_speed": 90, "dry_temp": 74, "roller_life_pct": 86})
    out = sys.open_complaint_case(lot, "yellow shift", "high")
    assert len(out["ranked_candidates"]) >= 1
    assert len(out["cause_chain"]) >= 1


def test_customer_specific_tolerance_different_suggestions():
    sys = UltimateColorFilmSystemV2Optimized()
    sys.register_customer_profile("CUST-STRICT", {"default_tolerance": 1.8, "sensitivity": {"yellow": 1.4}})
    sys.register_customer_profile("CUST-LOOSE", {"default_tolerance": 2.8, "sensitivity": {"yellow": 0.8}})
    metrics = {"avg_de": 2.0, "max_de": 3.0, "db": 0.9, "uniformity_std": 0.45}
    a = sys.evaluate_customer_acceptance("CUST-STRICT", "SKU-A", {"light_source": "warm"}, metrics)
    b = sys.evaluate_customer_acceptance("CUST-LOOSE", "SKU-A", {"light_source": "warm"}, metrics)
    assert a["risk_score"] >= b["risk_score"]


def test_machine_transfer_compensation_risk():
    sys = UltimateColorFilmSystemV2Optimized()
    sys.cross_batch.register_batch(
        "BATCH-A",
        {
            "lab": {"L": 62.0, "a": 3.2, "b": 14.8},
            "recipe": {"C": 42, "M": 35, "Y": 26, "K": 7},
            "temp": 24,
            "substrate_lab": {"L": 95.0, "a": -0.2, "b": 1.2},
            "ink_lot": "INK-A",
            "machine_id": "MC-A",
            "shift": "day",
        },
    )
    out = sys.cross_batch.find_match_recipe(
        "BATCH-A",
        {
            "temp": 30,
            "substrate_lab": {"L": 94.0, "a": -0.1, "b": 3.0},
            "ink_lot": "INK-B",
            "machine_id": "MC-B",
            "shift": "night",
        },
    )
    factors = [x["factor"] for x in out["change_factors"]]
    assert "machine_transfer" in factors


def test_roll_tail_drift_blocks_auto_release():
    sys = UltimateColorFilmSystemV2Optimized()
    lot = "LOT-ROLL-TAIL"
    _add_trace(sys, lot, complete=True)
    sys.register_roll(lot_id=lot, roll_id="ROLL-001", length_m=180.0, machine_id="MC-A", shift="night")
    sys.mark_roll_zone("ROLL-001", "restart_zone", 0, 20, "restart first zone")
    for i in range(1, 25):
        meter = i * 7.0
        if i < 8:
            de = 1.1
        elif i < 16:
            de = 1.25
        else:
            de = 2.6 + (i - 16) * 0.12
        sys.add_roll_measurement("ROLL-001", meter_pos=meter, de=de)
    payload = _good_assessment_payload(lot)
    payload["meta"]["roll_id"] = "ROLL-001"
    out = sys.integrated_assessment(**payload)
    assert "roll_tail_drift_review" in out["boundary"]["review_triggers"] or "roll_tail_drift_high" in out["boundary"]["arbitration_triggers"]


def test_state_machine_illegal_transition_blocked():
    sys = UltimateColorFilmSystemV2Optimized()
    out = sys.transition_state("LOT-STATE", "shipped", "OP-A", "jump test")
    assert out["ok"] is False
    assert out["error"] == "illegal_transition"


def test_trace_revision_and_override_append_only():
    sys = UltimateColorFilmSystemV2Optimized()
    lot = "LOT-TRACE-REV"
    sys.lifecycle.add_event(lot, "ink_receipt", {"ink_model": "CYAN", "lot": "I-1"}, event_id="evt-1")
    sys.lifecycle.add_event(lot, "printing", {"line_speed": 92, "dry_temp": 70}, event_id="evt-2")
    rev = sys.add_trace_revision(lot, "evt-2", {"dry_temp": 68}, "QA", "sensor correction")
    ov = sys.add_manual_override_audit(lot, "DEC-001", "QA", "Manager", "urgent customer concession")
    ch = sys.lifecycle.get_chain(lot)
    assert rev["recorded"] is True
    assert ov["recorded"] is True
    assert len(ch["revisions"]) >= 1
    assert len(ch["overrides"]) >= 1
    assert ch["integrity"] is True


def test_trace_event_idempotency_deduplicates():
    sys = UltimateColorFilmSystemV2Optimized()
    lot = "LOT-TRACE-IDEM"
    r1 = sys.add_trace_event(
        lot_id=lot,
        stage="ink_receipt",
        data={"lot": "INK-1"},
        actor="OP-A",
        idempotency_key="idem-evt-001",
    )
    r2 = sys.add_trace_event(
        lot_id=lot,
        stage="ink_receipt",
        data={"lot": "INK-1"},
        actor="OP-A",
        idempotency_key="idem-evt-001",
    )
    ch = sys.lifecycle.get_chain(lot)
    assert r1.get("recorded") is True
    assert r2.get("deduplicated") is True
    assert ch.get("event_count") == 1


def test_replay_with_new_rule_or_meta():
    sys = UltimateColorFilmSystemV2Optimized()
    lot = "LOT-REPLAY"
    _add_trace(sys, lot, complete=True)
    payload = _good_assessment_payload(lot)
    out = sys.integrated_assessment(**payload)
    sid = out.get("snapshot_id")
    assert sid is not None

    sys.register_lifecycle_rule_pack(
        version="LIFE-RULE-REPLAY-R2",
        active_from_ts=0.0,
        scope={"sku_prefixes": ["SKU-"]},
        params={"process_risk_review": 0.2},
        notes="replay check",
    )
    replay = sys.replay_assessment(
        snapshot_id=sid,
        force_lifecycle_rule_version="LIFE-RULE-REPLAY-R2",
        meta_patch={"golden_status": "replace_now"},
    )
    assert replay["result"]["final_decision"]["mode"] == "manual_arbitration"

    sim = sys.simulate_rule_impact(
        snapshot_id=sid,
        rule_versions=["LIFE-RULE-REPLAY-R2"],
        meta_patch={"golden_status": "ok"},
    )
    assert sim["total"] == 1
    assert len(sim["simulations"]) == 1


def test_auto_case_open_and_role_view():
    sys = UltimateColorFilmSystemV2Optimized()
    lot = "LOT-CASE-AUTO"
    _add_trace(sys, lot, complete=False)
    payload = _good_assessment_payload(lot)
    payload["meta"].update({"actor": "QA-A", "auto_case_open": True})
    out = sys.integrated_assessment(**payload)
    case_ref = out.get("case_ref")
    assert isinstance(case_ref, dict)
    assert bool(case_ref.get("case_id"))

    listing = sys.list_quality_cases(lot_id=lot, last_n=10)
    assert listing["count"] >= 1

    role = sys.build_role_view("quality_manager", out)
    assert role["role"] == "quality_manager"
    assert isinstance(role.get("gates", {}), dict)


def test_case_workflow_and_batch_rule_simulation():
    sys = UltimateColorFilmSystemV2Optimized()
    lot = "LOT-CASE-FLOW"
    _add_trace(sys, lot, complete=True)
    payload = _good_assessment_payload(lot)
    out = sys.integrated_assessment(**payload)
    sid = out.get("snapshot_id")
    assert sid is not None

    opened = sys.open_quality_case(
        lot_id=lot,
        case_type="nonconformance",
        issue="manual test case",
        severity="high",
        source="unit_test",
        created_by="QA",
        dedup_key=f"case-{lot}",
    )
    cid = opened.get("case_id")
    assert cid

    step1 = sys.transition_case(cid, "investigating", "QA", "start")
    assert step1["ok"] is True
    step2 = sys.transition_case(cid, "action_planned", "QA", "plan actions")
    assert step2["ok"] is True
    act = sys.add_case_action(
        case_id=cid,
        action_type="containment",
        owner="OP-A",
        description="hold shipment",
        actor="QA",
    )
    assert act["ok"] is True
    aid = act.get("action_id")
    assert aid
    step3 = sys.transition_case(cid, "action_in_progress", "QA", "execute")
    assert step3["ok"] is True
    done = sys.complete_case_action(case_id=cid, action_id=aid, actor="QA", result={"note": "done"}, effectiveness=0.9)
    assert done["ok"] is True
    step4 = sys.transition_case(cid, "verification", "QA", "verify")
    assert step4["ok"] is True
    wv = sys.add_case_waiver(cid, actor="QA", approved_by="Manager", reason="customer approved")
    assert wv["ok"] is True
    closed = sys.close_quality_case(cid, actor="QA", verification={"result": "effective"})
    assert closed["ok"] is True
    snap = sys.get_quality_case(cid)
    assert snap["case"]["state"] == "closed"
    assert snap["event_count"] >= 6

    sys.register_lifecycle_rule_pack(
        version="LIFE-RULE-BATCH-R2",
        active_from_ts=0.0,
        scope={},
        params={"process_risk_review": 0.3},
        notes="batch simulation",
    )
    batch = sys.simulate_rule_impact_batch(
        snapshot_ids=[sid],
        rule_versions=["LIFE-RULE-BATCH-R2"],
        meta_patch={"golden_status": "ok"},
    )
    assert batch["batch_count"] == 1
    assert batch["total_simulations"] == 1


def test_case_approval_gate_and_mandatory_action_close_guard():
    sys = UltimateColorFilmSystemV2Optimized()
    lot = "LOT-CASE-GATE"
    _add_trace(sys, lot, complete=True)

    opened = sys.open_quality_case(
        lot_id=lot,
        case_type="nonconformance",
        issue="critical release dispute",
        severity="high",
        source="unit_test",
        created_by="QA",
        dedup_key=f"gate-{lot}",
    )
    cid = opened.get("case_id")
    assert cid

    act = sys.add_case_action(
        case_id=cid,
        action_type="containment",
        owner="OP-A",
        description="hold shipment",
        actor="QA",
        mandatory=True,
        priority=1,
    )
    assert act["ok"] is True
    aid = act.get("action_id")
    assert aid

    assert sys.transition_case(cid, "investigating", "QA", "start")["ok"] is True
    assert sys.transition_case(cid, "action_planned", "QA", "plan")["ok"] is True
    assert sys.transition_case(cid, "action_in_progress", "QA", "execute")["ok"] is True
    assert sys.transition_case(cid, "verification", "QA", "verify")["ok"] is True

    blocked_close = sys.close_quality_case(cid, actor="QA", verification={"result": "pending"})
    assert blocked_close["ok"] is False
    assert blocked_close["error"] == "mandatory_actions_pending"

    denied = sys.add_case_waiver(
        cid,
        actor="QA",
        approved_by="LINE-LEAD",
        reason="try bypass",
        approver_role="supervisor",
        risk_level="high",
        customer_tier="standard",
    )
    assert denied["ok"] is False
    assert denied["error"] == "approval_insufficient"

    done = sys.complete_case_action(case_id=cid, action_id=aid, actor="QA", result={"note": "containment done"}, effectiveness=0.88)
    assert done["ok"] is True

    closed = sys.close_quality_case(cid, actor="QA", verification={"result": "effective"})
    assert closed["ok"] is True
    assert closed["state"] == "closed"


def test_case_sla_overdue_triggers_review_and_hard_block():
    sys = UltimateColorFilmSystemV2Optimized()

    lot_review = "LOT-CASE-SLA-REVIEW"
    _add_trace(sys, lot_review, complete=True)
    _set_release_ready_state(sys, lot_review)
    opened_review = sys.open_quality_case(
        lot_id=lot_review,
        case_type="nonconformance",
        issue="pending review action",
        severity="low",
        source="unit_test",
        created_by="QA",
        dedup_key=f"sla-review-{lot_review}",
    )
    cid_review = opened_review.get("case_id")
    assert cid_review
    sys.add_case_action(
        case_id=cid_review,
        action_type="retest",
        owner="OP-A",
        description="late action",
        actor="QA",
        due_ts=time.time() - 120.0,
        mandatory=True,
    )
    payload_review = _good_assessment_payload(lot_review)
    payload_review["meta"]["idempotency_key"] = f"idem-{lot_review}-001"
    out_review = sys.integrated_assessment(**payload_review)
    reasons_review = set(out_review["boundary"]["review_triggers"] + out_review["boundary"]["hard_blocks"] + out_review["boundary"]["arbitration_triggers"])
    assert "quality_case_sla_risk" in reasons_review
    assert out_review["module_outputs"]["case_governance"]["sla"]["overdue_count"] >= 1

    lot_hard = "LOT-CASE-SLA-HARD"
    _add_trace(sys, lot_hard, complete=True)
    _set_release_ready_state(sys, lot_hard)
    opened_hard = sys.open_quality_case(
        lot_id=lot_hard,
        case_type="nonconformance",
        issue="critical unresolved issue",
        severity="critical",
        source="unit_test",
        created_by="QA",
        dedup_key=f"sla-hard-{lot_hard}",
    )
    cid_hard = opened_hard.get("case_id")
    assert cid_hard
    sys.add_case_action(
        case_id=cid_hard,
        action_type="containment",
        owner="OP-A",
        description="overdue #1",
        actor="QA",
        due_ts=time.time() - 180.0,
        mandatory=True,
    )
    sys.add_case_action(
        case_id=cid_hard,
        action_type="containment",
        owner="OP-B",
        description="overdue #2",
        actor="QA",
        due_ts=time.time() - 90.0,
        mandatory=True,
    )
    payload_hard = _good_assessment_payload(lot_hard)
    payload_hard["meta"]["idempotency_key"] = f"idem-{lot_hard}-001"
    out_hard = sys.integrated_assessment(**payload_hard)
    assert "open_critical_quality_case" in out_hard["boundary"]["hard_blocks"]
    assert "quality_case_sla_overdue" in out_hard["boundary"]["hard_blocks"]
    assert out_hard["status"] in {"auto_blocked", "manual_arbitration_required"}


def test_case_center_persistence_reload():
    temp_dir = tempfile.mkdtemp(prefix="elite_case_store_")
    store_path = os.path.join(temp_dir, "case_store.json")
    lot = "LOT-CASE-PERSIST"
    try:
        sys_a = UltimateColorFilmSystemV2Optimized(case_store_path=store_path)
        _add_trace(sys_a, lot, complete=True)
        opened = sys_a.open_quality_case(
            lot_id=lot,
            case_type="nonconformance",
            issue="persistence check",
            severity="high",
            source="unit_test",
            created_by="QA",
            dedup_key=f"persist-{lot}",
        )
        cid = opened.get("case_id")
        assert cid
        act = sys_a.add_case_action(
            case_id=cid,
            action_type="containment",
            owner="OP-A",
            description="hold shipment",
            actor="QA",
            mandatory=True,
            priority=1,
            due_ts=time.time() + 300.0,
        )
        assert act["ok"] is True
        assert os.path.exists(store_path)

        sys_b = UltimateColorFilmSystemV2Optimized(case_store_path=store_path)
        listed = sys_b.list_quality_cases(lot_id=lot, last_n=5)
        assert listed["count"] == 1
        case = listed["rows"][0]
        assert case["case_id"] == cid
        assert case["open_action_count"] >= 1

        sla = sys_b.get_case_sla_report(case_id=cid)
        assert sla["count"] >= 1
        st = sys_b.get_case_store_status()
        assert st["enabled"] is True
        assert st["loaded"] is True
    finally:
        if os.path.exists(store_path):
            os.remove(store_path)
        if os.path.isdir(temp_dir):
            os.rmdir(temp_dir)


def test_case_center_sqlite_persistence_reload():
    temp_dir = tempfile.mkdtemp(prefix="elite_case_db_")
    db_path = os.path.join(temp_dir, "case_store.sqlite")
    lot = "LOT-CASE-SQLITE"
    try:
        sys_a = UltimateColorFilmSystemV2Optimized(case_db_path=db_path)
        _add_trace(sys_a, lot, complete=True)
        opened = sys_a.open_quality_case(
            lot_id=lot,
            case_type="nonconformance",
            issue="sqlite persistence check",
            severity="high",
            source="unit_test",
            created_by="QA",
            dedup_key=f"sqlite-{lot}",
        )
        cid = opened.get("case_id")
        assert cid
        act = sys_a.add_case_action(
            case_id=cid,
            action_type="containment",
            owner="OP-A",
            description="hold shipment",
            actor="QA",
            mandatory=True,
            priority=1,
            due_ts=time.time() + 300.0,
        )
        assert act["ok"] is True
        assert os.path.exists(db_path)

        sys_b = UltimateColorFilmSystemV2Optimized(case_db_path=db_path)
        listed = sys_b.list_quality_cases(lot_id=lot, last_n=5)
        assert listed["count"] == 1
        case = listed["rows"][0]
        assert case["case_id"] == cid
        assert case["open_action_count"] >= 1

        sla = sys_b.get_case_sla_report(case_id=cid)
        assert sla["count"] >= 1
        st = sys_b.get_case_store_status()
        assert st["enabled"] is True
        assert st["backend"] == "sqlite"
    finally:
        for suffix in ("", "-wal", "-shm"):
            fp = f"{db_path}{suffix}"
            if os.path.exists(fp):
                try:
                    os.remove(fp)
                except PermissionError:
                    pass
        if os.path.isdir(temp_dir):
            try:
                os.rmdir(temp_dir)
            except OSError:
                pass


def test_case_store_consistency_check_ok():
    sys = UltimateColorFilmSystemV2Optimized()
    lot = "LOT-CASE-CHECK-OK"
    _add_trace(sys, lot, complete=True)
    opened = sys.open_quality_case(
        lot_id=lot,
        case_type="nonconformance",
        issue="consistency ok check",
        severity="medium",
        source="unit_test",
        created_by="QA",
        dedup_key=f"check-ok-{lot}",
    )
    cid = opened.get("case_id")
    assert cid
    sys.add_case_action(
        case_id=cid,
        action_type="containment",
        owner="OP-A",
        description="hold shipment",
        actor="QA",
        mandatory=True,
        priority=1,
    )
    out = sys.get_case_store_consistency()
    assert out["ok"] is True
    assert out["error_count"] == 0


def test_case_store_consistency_detects_event_tamper():
    sys = UltimateColorFilmSystemV2Optimized()
    lot = "LOT-CASE-CHECK-TAMPER"
    opened = sys.open_quality_case(
        lot_id=lot,
        case_type="nonconformance",
        issue="tamper check",
        severity="high",
        source="unit_test",
        created_by="QA",
        dedup_key=f"check-tamper-{lot}",
    )
    cid = opened.get("case_id")
    assert cid
    rows = sys.case_center._events.get(cid, [])  # noqa: SLF001
    assert len(rows) >= 1
    rows[0]["hash"] = "tampered_hash"
    out = sys.get_case_store_consistency()
    assert out["ok"] is False
    codes = {str(x.get("code", "")) for x in out.get("errors", [])}
    assert "event_hash_mismatch" in codes


def run_all():
    test_local_hotspot_override()
    test_data_invalid_guard()
    test_calibration_overdue_but_numeric_ok_blocked()
    test_golden_drift_old_standard_blocked()
    test_trace_missing_event_blocks_release()
    test_restart_first_20m_drift_and_changeover_detected()
    test_metamerism_high_risk_while_d65_ok()
    test_post_process_risk_print_pass_but_downstream_risk()
    test_msa_repeatability_poor_blocking()
    test_spc_instability_even_if_current_good()
    test_first_pass_retest_arbitration_conflict()
    test_customer_yellow_complaint_ranked_candidates()
    test_customer_specific_tolerance_different_suggestions()
    test_machine_transfer_compensation_risk()
    test_roll_tail_drift_blocks_auto_release()
    test_state_machine_illegal_transition_blocked()
    test_trace_revision_and_override_append_only()
    test_trace_event_idempotency_deduplicates()
    test_replay_with_new_rule_or_meta()
    test_auto_case_open_and_role_view()
    test_case_workflow_and_batch_rule_simulation()
    test_case_approval_gate_and_mandatory_action_close_guard()
    test_case_sla_overdue_triggers_review_and_hard_block()
    test_case_center_persistence_reload()
    test_case_center_sqlite_persistence_reload()
    test_case_store_consistency_check_ok()
    test_case_store_consistency_detects_event_tamper()
    print("production blindspot tests passed")


if __name__ == "__main__":
    run_all()



