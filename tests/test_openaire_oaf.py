"""Испытания коннектора OpenAIRE (ИД-27, ред. 1.5.2).

Основание — четвёртая выгрузка журнала (25.11.2026): пять записей
«http:CON-OPENAIRE HTTP 405» — путь Graph API `graph/v1/researchProducts`
отвечает «No static resource v1/researchProducts» на любой запрос, источник
был потерян. Живая проверка 25.11.2026 показала рабочий контур
`/search/researchProducts?keywords=…&format=json` (ответ OAF JSON) и то, что
кириллический `keywords` даёт HTTP 409 «Syntax errors. expected boolean».

OAF-01 — разбор ответа OAF: заголовок, DOI, дата, язык, авторы.
OAF-02 — поле приходит то объектом, то списком — оба вида разбираются.
OAF-03 — кириллическое выражение честно отклоняется (E_POLICY), запроса нет.
OAF-04 — латинская часть смешанного выражения используется.
OAF-05 — HTTP 405 включает запасной путь Graph API.
OAF-06 — плавающий HTTP 409 повторяется один раз.
OAF-07 — реестр указывает рабочий адрес контура.
OAF-08 — логические операторы убираются: «6G OR IMT-2030» даёт HTTP 409.
OAF-09 — в смешанной ветви русские термы не вытесняют англоязычные.
OAF-10 — пустой ответ на узкий запрос ослабляется до 2 и 1 терма.
"""
from __future__ import annotations

import json
from unittest import mock

from isheika.contracts import CoreError
from isheika.search import connectors as CN
from isheika.storage import db

from .base import BaseCase


def _oaf_response() -> dict:
    """Ответ /search/researchProducts?format=json в сокращённом, но реальном виде."""
    return {"response": {"results": {"result": [
        {"metadata": {"oaf:entity": {"oaf:result": {
            "title": [{"@classid": "main title", "$": "Terahertz communications for 6G networks"},
                      {"@classid": "subtitle", "$": "a survey"}],
            "creator": [{"$": "Ivanov I."}, {"$": "Petrov P."}],
            "pid": [{"@classid": "doi", "$": "10.1000/test-6g"},
                    {"@classid": "pmid", "$": "12345"}],
            "url": {"$": "https://example.org/6g-survey"},
            "dateofacceptance": {"$": "2024-03-01"},
            "description": {"$": "<p>Survey of <b>terahertz</b> links.</p>"},
            "language": {"@classid": "eng"},
            "resourcetype": {"@classid": "Article"},
            "originalId": {"$": "oai:openaire:1"},
        }}}},
        {"metadata": {"oaf:entity": {"oaf:result": {
            "title": {"$": "Tropospheric scatter measurements"},
            "creator": {"$": "Sidorov S."},
            "pid": {"@classid": "doi", "$": "10.1000/test-tro"},
            "dateofacceptance": "2022-07-15",
            "language": {"@classid": "und"},
        }}}},
    ]}}}


class OpenAireOafTests(BaseCase):
    def setUp(self) -> None:
        super().setUp()
        meta = db.dec(db.one("SELECT * FROM registry_connectors WHERE code='CON-OPENAIRE'"),
                      "capabilities", "limits", "quota_policy")
        self.conn = CN.build_connector(meta)
        self.assertIsNotNone(self.conn)

    def test_OAF_01_parses_search_api_response(self):
        with mock.patch.object(self.conn, "get_json", return_value=_oaf_response()) as gj:
            docs = self.conn.search("(6G)", limit=5)
        url = gj.call_args[0][0]
        self.assertIn("/search/researchProducts", url)
        self.assertIn("format=json", url)
        self.assertNotIn("graph/v1", url)
        self.assertEqual(len(docs), 2)
        first = docs[0]
        self.assertEqual(first.title, "Terahertz communications for 6G networks")
        self.assertEqual(first.doi, "10.1000/test-6g")
        self.assertEqual(first.published_at, "2024-03-01")
        self.assertEqual(first.language, "en")
        self.assertEqual(first.authors, ["Ivanov I.", "Petrov P."])
        self.assertNotIn("<", first.abstract)

    def test_OAF_02_object_and_list_fields_both_parsed(self):
        with mock.patch.object(self.conn, "get_json", return_value=_oaf_response()):
            docs = self.conn.search("tropospheric scatter", limit=5)
        second = docs[1]
        self.assertEqual(second.title, "Tropospheric scatter measurements")
        self.assertEqual(second.authors, ["Sidorov S."])
        self.assertEqual(second.published_at, "2022-07-15")
        self.assertEqual(second.url, "https://doi.org/10.1000/test-tro")
        self.assertIsNone(second.language)      # «und» — язык не определён

    def test_OAF_03_cyrillic_expression_is_rejected_without_request(self):
        with mock.patch.object(self.conn, "get_json") as gj:
            with self.assertRaises(CoreError) as ctx:
                self.conn.search("(тропосферная связь)", limit=5)
        self.assertEqual(ctx.exception.error.code, "E_POLICY")
        self.assertIn("латиниц", ctx.exception.error.message)
        gj.assert_not_called()

    def test_OAF_04_latin_part_of_mixed_expression_is_used(self):
        with mock.patch.object(self.conn, "get_json", return_value=_oaf_response()) as gj:
            self.conn.search('(6G OR "терагерцовая связь")', limit=5)
        url = gj.call_args[0][0]
        self.assertIn("keywords=6G", url)
        self.assertNotIn("терагерц", url)

    def test_OAF_05_http_405_falls_back_to_graph_api(self):
        graph = {"results": [{"mainTitle": "6G roadmap", "id": "oai:1",
                              "websiteUrl": "https://example.org/roadmap",
                              "pids": [{"value": "10.1000/roadmap"}],
                              "publicationDate": "2023-01-01",
                              "language": {"code": "eng"}, "type": "Article"}]}
        answers = [CoreError("E_NETWORK", "CON-OPENAIRE: HTTP 405 No static resource v1/researchProducts"),
                   graph]
        with mock.patch.object(self.conn, "get_json", side_effect=answers) as gj:
            docs = self.conn.search("6G", limit=5)
        self.assertEqual(gj.call_count, 2)
        self.assertIn("search=", gj.call_args[0][0])
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].title, "6G roadmap")
        self.assertEqual(docs[0].doi, "10.1000/roadmap")

    def test_OAF_06_floating_409_is_retried_once(self):
        flaky = CoreError("E_NETWORK", "CON-OPENAIRE: HTTP 409 Fail to execute search")
        with mock.patch.object(self.conn, "get_json", side_effect=[flaky, _oaf_response()]) as gj, \
             mock.patch("time.sleep") as sl:
            docs = self.conn.search("6G", limit=5)
        self.assertEqual(gj.call_count, 2)
        self.assertTrue(sl.called)
        self.assertEqual(len(docs), 2)
        # повтор только один: устойчивый 409 — честный отказ, а не цикл
        with mock.patch.object(self.conn, "get_json", side_effect=[flaky, flaky]) as gj2, \
             mock.patch("time.sleep"):
            with self.assertRaises(CoreError):
                self.conn.search("6G", limit=5)
        self.assertEqual(gj2.call_count, 2)

    def test_OAF_08_boolean_operators_are_stripped(self):
        """Живая проверка 25.11.2026: keywords с OR → 409, через пробел → 200."""
        with mock.patch.object(self.conn, "get_json", return_value=_oaf_response()) as gj:
            self.conn.search('(6G OR "sixth generation mobile" OR IMT-2030)', limit=5)
        url = gj.call_args[0][0]
        self.assertNotIn("OR", url.replace("researchProducts", ""))
        self.assertIn("keywords=6G%20", url)
        self.assertIn("IMT-2030", url)

    def test_OAF_09_russian_terms_do_not_displace_english(self):
        expr = ('("тропосферная связь" OR "тропосферное рассеяние" OR "тропосферная радиосвязь" '
                'OR "загоризонтная связь") OR ("tropospheric scatter" OR troposcatter)')
        with mock.patch.object(self.conn, "get_json", return_value=_oaf_response()) as gj:
            docs = self.conn.search(expr, limit=5)
        url = gj.call_args[0][0]
        self.assertTrue(docs)
        self.assertIn("troposcatter", url)
        self.assertNotIn("%D1%82", url)      # кириллицы в запросе нет

    def test_OAF_10_empty_answer_relaxes_the_query(self):
        empty = {"response": {"results": {"result": None}}}
        with mock.patch.object(self.conn, "get_json",
                               side_effect=[empty, empty, _oaf_response()]) as gj:
            docs = self.conn.search('"tropospheric scatter" troposcatter "radio propagation" horizon',
                                    limit=5)
        self.assertEqual(gj.call_count, 3)
        self.assertTrue(docs)
        first = gj.call_args_list[0][0][0]
        last = gj.call_args_list[-1][0][0]
        self.assertIn("horizon", first)
        self.assertNotIn("horizon", last)

    def test_OAF_07_registry_points_to_working_endpoint(self):
        row = db.one("SELECT * FROM registry_connectors WHERE code='CON-OPENAIRE'")
        self.assertIn("/search/researchProducts", row["base_url"] or "")
        limits = json.loads(row["limits"] or "{}")
        self.assertIn("25.11.2026", json.dumps(limits, ensure_ascii=False))
