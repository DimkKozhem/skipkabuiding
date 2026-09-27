"""Construction reference catalog from the DGP workbook."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from sitewatch.api.main import create_app
from sitewatch.catalog import construction
from sitewatch.settings import project_root


XLSX = (
    project_root()
    / "ТЗ "
    / "Датасет "
    / "7.ДГП_датасеты"
    / "Сводный перечень строительных работ_ЛТЦ.xlsx"
)

EXPECTED_TYPES = [
    ("housing", "Жильё"),
    ("education", "Образование"),
    ("healthcare", "Здравоохранение"),
    ("sport", "Спорт"),
    ("culture", "Культура"),
    ("admin", "Административные здания"),
    ("kindergarten", "ДОУ"),
    ("office", "Офисно-деловой центр"),
    ("roads", "Дороги"),
]


@pytest.fixture(autouse=True)
def _clear_catalog_cache():
    construction.clear_construction_catalog_cache()
    yield
    construction.clear_construction_catalog_cache()


@pytest.mark.skipif(not XLSX.is_file(), reason="DGP workbook is not present")
def test_construction_types_and_works_from_xlsx():
    types = construction.list_construction_types()
    assert [(item["id"], item["name"]) for item in types] == EXPECTED_TYPES

    housing = construction.list_works_for_type("housing")
    roads = construction.list_works_for_type("roads")
    assert housing["type"]["id"] == "housing"
    assert roads["type"]["id"] == "roads"

    housing_works = [
        work
        for group in housing["groups"]
        for work in group["works"]
    ]
    roads_works = [
        work
        for group in roads["groups"]
        for work in group["works"]
    ]
    assert len(housing_works) != len(roads_works)

    by_id = {work["id"]: work for work in housing_works}
    assert "w_10_01" in by_id
    assert by_id["w_10_01"]["name"] == "Отселение домов в пятне застройки"
    assert by_id["w_10_01"]["code"] == "10.01"

    for work in housing_works:
        assert "start_date" not in work
        assert "end_date" not in work
        assert "date" not in work
        for child in work.get("children") or []:
            assert "start_date" not in child
            assert "end_date" not in child
            assert "date" not in child


@pytest.mark.skipif(not XLSX.is_file(), reason="DGP workbook is not present")
def test_construction_catalog_api():
    client = TestClient(create_app())
    types = client.get("/api/catalog/construction-types")
    assert types.status_code == 200
    body = types.json()
    assert [(item["id"], item["name"]) for item in body] == EXPECTED_TYPES

    housing = client.get("/api/catalog/construction-types/housing/works")
    assert housing.status_code == 200
    payload = housing.json()
    assert payload["type"]["name"] == "Жильё"
    assert payload["groups"]
    works = [work for group in payload["groups"] for work in group["works"]]
    assert any(work["id"] == "w_10_01" for work in works)

    missing = client.get("/api/catalog/construction-types/not_a_type/works")
    assert missing.status_code == 404

    stages = client.get("/api/catalog/stages")
    assert stages.status_code == 200
    codes = {item["code"] for item in stages.json()}
    assert "foundation" in codes
    assert "excavation" in codes


def test_normalize_work_code_from_excel_datetime():
    from datetime import datetime

    assert construction.normalize_work_code(datetime(2025, 1, 10)) == "10.01"
    assert construction.normalize_work_code(datetime(2025, 1, 12)) == "12.01"
    assert construction.normalize_work_code("10.13.") == "10.13."
    assert construction.normalize_work_code(12) == "12"
    assert construction.normalize_work_code(None) is None
