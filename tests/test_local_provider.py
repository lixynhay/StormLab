"""LocalProvider refactor tests (t1-t6): structured report, no prompt scraping."""
import inspect
import re
from pathlib import Path

import ai.ai_analysis as ai_analysis
from ai.ai_providers import LocalProvider, OpenAICompatProvider, _rule_based_analysis
from core.season_regime import thresholds_for


def _cool_report():
    return {
        "cape": 400, "cin": -40, "lcl": 900, "lcl_height_m": 1200,
        "bulk_shear_06": 25, "bulk_shear_03": 14, "srh": 200,
        "stp": 0.4, "scp": 1.5, "dcape": 500,
        "k_index": 25, "total_totals": 45, "lifted_index": -3,
        "regime": "cool",
        "cape_interpretation": "🌨 Умеренная зимняя нестабильность — возможен thundersnow",
        "shear_interpretation": "🟠 Сильный (snow-squall / зимний шквал)",
        "cin_interpretation": "🟡 Слабая крышка — возможны снежные заряды",
        "lcl_interpretation": "🌨 Умеренный LCL — зимняя конвекция возможна",
    }


def _warm_report():
    r = _cool_report()
    r.update({
        "regime": "warm",
        "cape_interpretation": "слабая нестабильность",
        "shear_interpretation": "🟡 Умеренный (мультиячейковые грозы)",
    })
    return r


# t1
def test_cool_profile_is_winter_dangerous():
    text = _rule_based_analysis(_cool_report(), "Омск")
    assert "наиболее вероятный характер конвекции — зимняя конвекция" in text
    assert "thundersnow" in text
    assert "snow-squall" in text
    assert "торнадо-опасные суперячейки" not in text


# t2
def test_warm_low_shear_profile_is_not_dangerous():
    report = _warm_report()
    report.update({"cape": 300, "bulk_shear_06": 12, "dcape": 0})
    text = _rule_based_analysis(report, "Оклахома")
    assert "организованные грозы" not in text
    assert "значимые опасные явления маловероятны" in text


# t3
def test_cape_zero_is_no_convection_in_both_regimes():
    for regime in ("cool", "warm"):
        report = _cool_report()
        report.update({"cape": 0, "regime": regime})
        text = _rule_based_analysis(report, "Тест")
        assert "характер конвекции — конвекция маловероятна" in text
        assert "CAPE=0" in text


# t4
def test_bracketed_prompt_labels_cannot_cause_silent_zero():
    prompt = (
        "CAPE (SB): 9999 Дж/кг | CIN: 9999 | LCL: 9999 гПа\n"
        "🌪 STP (торнадо): 9.9 | ⚡ SCP (суперячейки): 9.9 | 💨 DCAPE (шквалы): 9999\n"
    )
    text = LocalProvider().generate(prompt, report=_cool_report(), city="Омск")
    assert "CAPE=400" in text          # from report, not the misleading prompt
    assert "9999" not in text
    assert "Сезонный режим: cool" in text


# t5
def test_regime_read_from_report_not_prompt():
    prompt = "Просто произвольный текст без строки «Сезонный режим»."
    text = LocalProvider().generate(prompt, report=_cool_report(), city="Омск")
    assert "Сезонный режим: cool" in text
    assert "thundersnow" in text


# t6
def test_no_unverified_literal_thresholds_in_rule_based_analysis():
    source = inspect.getsource(_rule_based_analysis)
    # The only numeric comparison literals allowed are 0 (cape guard) and
    # 1000 J/kg DCAPE (SPC params2.html). Every season-sensitive number must
    # come from thresholds_for(regime).
    literals = set(re.findall(r"[<>]=?\s*(\d+(?:\.\d+)?)", source))
    assert literals <= {"0", "1000"}, literals
    assert "thresholds_for(regime)" in source
    for key in ("cape_min", "shear06_min", "lcl_max", "cin_max"):
        assert f"th['{key}']" in source or f'th["{key}"]' in source
    # season_regime remains the only numeric source of truth
    th_cool = thresholds_for("cool")
    assert (th_cool["cape_min"], th_cool["shear06_min"]) == (200, 20)


def test_external_providers_keep_prompt_only_signature():
    assert "report" not in inspect.signature(OpenAICompatProvider.generate).parameters
    assert "report" not in inspect.signature(
        ai_analysis._chain[0].__class__.generate
    ).parameters or getattr(ai_analysis._chain[0], "accepts_report", False)


def test_no_scraper_helpers_left():
    module_source = Path("ai/ai_providers.py").read_text(encoding="utf-8")
    assert "_parse_prompt_data" not in module_source
    assert "_parse_city" not in module_source
    assert "re.search" not in module_source


# ------------------------------------------------------------------ 2.6 None-guard

# t7
def test_okc_winter_none_eff_fields_are_rendered_as_nd():
    report = _cool_report()
    report.update({
        "dcape": None, "stp_eff": None, "scp_eff": None,
        "ehi": None, "brn": None, "sweat_index": None, "showalter_index": None,
        "stp": 0.0, "scp": 0.0,
    })
    text = LocalProvider().generate("prompt ignored", report=report, city="OKC")
    assert "STP(effective)=н/д" in text
    assert "SCP(effective)=н/д" in text
    assert "DCAPE=н/д Дж/кг" in text
    assert "EHI=н/д" in text and "BRN=н/д" in text
    assert "STP(fixed)=0.0" in text and "SCP(fixed)=0.0" in text
    assert "н/д" in text  # nothing crashed to TypeError/ValueError


# t8
def test_cape_zero_with_dcape_none_is_no_convection_and_no_crash():
    report = _cool_report()
    report.update({"cape": 0, "dcape": None, "stp_eff": None, "scp_eff": None})
    text = LocalProvider().generate(report=report, city="Тест")
    assert "характер конвекции — конвекция маловероятна" in text
    assert "DCAPE=н/д Дж/кг" in text
    assert "STP(effective)=н/д" in text


# t9
def test_t1_to_t6_still_green_after_none_guard():
    for fn in (
        test_cool_profile_is_winter_dangerous,
        test_warm_low_shear_profile_is_not_dangerous,
        test_cape_zero_is_no_convection_in_both_regimes,
        test_bracketed_prompt_labels_cannot_cause_silent_zero,
        test_regime_read_from_report_not_prompt,
        test_no_unverified_literal_thresholds_in_rule_based_analysis,
    ):
        fn()
