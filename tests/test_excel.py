import io

import openpyxl
from conftest import auth, create_report, setup_admin


def test_excel_export_matches_form(client):
    token, _ = setup_admin(client)
    report = create_report(client, token)

    response = client.get(f"/api/reports/{report['id']}/excel", headers=auth(token))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    disposition = response.headers["content-disposition"]
    assert "filename*=UTF-8''" in disposition

    workbook = openpyxl.load_workbook(io.BytesIO(response.content), data_only=False)
    assert workbook.sheetnames == ["Отчет к заполнению"]

    sheet = workbook["Отчет к заполнению"]
    assert sheet["F16"].value == 26
    assert sheet["H16"].value == "октября"
    assert sheet["L16"].value == 2026
    assert sheet["E18"].value == "Кухаренко Юлия Владимировна"
    assert sheet["E22"].value == "Командировочные расходы"
    assert sheet["M26"].value == 99
    assert sheet["A36"].value == "22.10.2026-23.10.2026"
    assert sheet["C37"].value == "Проездной билет"
    assert sheet["E37"].value == "ЖЕ2110185790394"
    assert sheet["P37"].value == 28.45
    assert sheet["M29"].value == 99
    assert sheet["M30"].value == 89.45
    assert sheet["M31"].value == 9.55
    assert sheet["P46"].value == 89.45
    assert sheet["F52"].value == 89.45
    assert sheet["I6"].value == "Восемьдесят девять рублей 45 копеек"
    assert sheet["K49"].value == "Кухаренко Юлия Владимировна"
    # Формулы заменены значениями, чтобы файл корректно открывался без макросов
    assert sheet["S4"].value == "Восемьдесят девять рублей 45 копеек"


def test_spa_index_and_static(client):
    index = client.get("/")
    assert index.status_code == 200
    assert "Авансовые отчёты" in index.text
    assert "/static/app.js" in index.text

    script = client.get("/static/app.js")
    assert script.status_code == 200
    assert "amountInWords" in script.text

    styles = client.get("/static/styles.css")
    assert styles.status_code == 200
    assert "@page" in styles.text

    favicon = client.get("/favicon.svg")
    assert favicon.status_code == 200
