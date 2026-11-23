import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from feed.papers import PaperLibrary, brief, crossref_paper, paper_references, paper_topics, papers_in_topic, search_papers


class PaperTests(unittest.TestCase):
    def test_openalex_taxonomy_is_paginated_and_normalized(self):
        def entry(identifier, name):
            return {
                "id": f"https://openalex.org/subfields/{identifier}",
                "display_name": name,
                "field": {"display_name": "Computer Science"},
                "domain": {"display_name": "Physical Sciences"},
            }
        with patch("feed.papers.get_json", side_effect=[
            {"meta": {"count": 101}, "results": [entry(1712, "Software")]},
            {"results": [entry(1702, "Artificial Intelligence")]},
        ]) as request:
            paper_topics.cache_clear()
            try:
                topics = paper_topics()
                self.assertEqual([topic["id"] for topic in topics], ["1702", "1712"])
                self.assertEqual(topics[0]["field"], "Computer Science")
                self.assertEqual(request.call_args.args[1]["page"], 2)
            finally:
                paper_topics.cache_clear()

    def test_topic_works_use_exact_subfield_and_include_oa_metadata(self):
        work = {
            "display_name": "Topic paper",
            "doi": "https://doi.org/10.1234/topic",
            "publication_date": "2025-02-01",
            "abstract_inverted_index": {"paper.": [1], "A": [0]},
            "best_oa_location": {"pdf_url": "https://example.org/topic.pdf"},
            "primary_topic": {
                "domain": {"display_name": "Physical Sciences"},
                "field": {"display_name": "Computer Science"},
                "subfield": {"display_name": "Artificial Intelligence"},
            },
        }
        with patch("feed.papers.get_json", return_value={"meta": {"count": 20}, "results": [work]}) as request:
            result = papers_in_topic("1702", 1, "cited")
        self.assertIn("primary_topic.subfield.id:1702", request.call_args.args[1]["filter"])
        self.assertEqual(request.call_args.args[1]["sort"], "cited_by_count:desc")
        self.assertEqual(result["papers"][0]["groups"][2], "Artificial Intelligence")
        self.assertEqual(result["papers"][0]["summary"], "A paper.")
        self.assertEqual(result["papers"][0]["pdf_url"], "https://example.org/topic.pdf")

    def test_empty_topic_uses_crossref_with_the_requested_order_and_page(self):
        responses = [
            {"meta": {"count": 0}, "results": []},
            {
                "display_name": "Bioengineering",
                "domain": {"display_name": "Physical Sciences"},
                "field": {"display_name": "Chemical Engineering"},
            },
            {"message": {"total-results": 30, "items": [{"DOI": "10.1234/bio", "title": ["Bioengineering"]}]}},
        ]
        with patch("feed.papers.get_json", side_effect=responses) as request:
            result = papers_in_topic("1502", 2, "cited")
        self.assertEqual(result["source"], "crossref")
        self.assertEqual(result["topic_path"], ["Physical Sciences", "Chemical Engineering", "Bioengineering"])
        self.assertEqual(result["papers"][0]["doi"], "10.1234/bio")
        self.assertTrue(result["has_next"])
        self.assertEqual(request.call_args.args[1]["query.bibliographic"], "Bioengineering")
        self.assertEqual(request.call_args.args[1]["sort"], "is-referenced-by-count")
        self.assertEqual(request.call_args.args[1]["offset"], 12)

    def test_arxiv_search_returns_public_pdf_and_short_summary(self):
        attributes = {
            "doi": "10.48550/arxiv.1706.03762",
            "titles": [{"title": "A title"}],
            "creators": [{"name": "Researcher"}],
            "publicationYear": 2017,
            "descriptions": [{"descriptionType": "Abstract", "description": "<p>Summary</p>"}],
        }
        with patch("feed.papers.get_json", return_value={
            "meta": {"total": 30}, "data": [{"attributes": attributes}],
        }) as request:
            results = search_papers("arxiv", "AI + robotics", 2, "recent")
        self.assertEqual(request.call_args.args[1]["prefix"], "10.48550")
        self.assertEqual(request.call_args.args[1]["page[number]"], 2)
        self.assertEqual(results["papers"][0]["summary"], "Summary")
        self.assertEqual(results["papers"][0]["pdf_url"], "https://arxiv.org/pdf/1706.03762")
        self.assertTrue(results["has_next"])
        self.assertLessEqual(len(brief("body " * 500)), 901)

    def test_crossref_abstract_preserves_paragraph_spacing_and_uses_doi(self):
        paper = crossref_paper({
            "DOI": "10.1234/example",
            "title": ["Test &amp; result"],
            "abstract": "<jats:p>First.</jats:p><jats:p>Second.</jats:p>",
            "published": {"date-parts": [[2024]]},
        })
        self.assertEqual(paper["title"], "Test & result")
        self.assertEqual(paper["summary"], "First. Second.")
        self.assertEqual(paper["url"], "https://doi.org/10.1234/example")
        self.assertIsNone(paper["pdf_url"])

    def test_references_prefer_openalex_ids_and_fall_back_to_crossref(self):
        work = {"referenced_works": ["https://openalex.org/W12345"] * 2}
        crossref = {"reference": [{"DOI": "10.1234/a", "article-title": "Example"}]}
        with patch("feed.papers.optional_json", return_value={"results": [
            {"id": "https://openalex.org/W12345", "doi": "https://doi.org/10.1234/a"},
        ]}):
            [reference] = paper_references(work, crossref)
        self.assertEqual(reference["id"], "https://openalex.org/W12345")
        self.assertEqual(reference["title"], "Example")
        self.assertEqual(paper_references({}, crossref)[0]["doi"], "10.1234/a")

    def test_library_persists_papers_and_deduplicates_retries(self):
        payload = {"doi": "10.1234/example", "date": "2024-01-01", "groups": ["A", "B", "C"], "references": []}
        with TemporaryDirectory() as folder, patch("feed.papers.fetch_paper", return_value=payload) as fetch:
            database = Path(folder) / "papers.sqlite3"
            saved, added = PaperLibrary(database).save("crossref", payload["doi"])
            self.assertTrue(added)
            self.assertEqual(PaperLibrary(database).list(), [saved])
            self.assertEqual(PaperLibrary(database).save("crossref", payload["doi"]), (saved, False))
            fetch.assert_called_once()
