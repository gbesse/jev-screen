"""Purpose: Parser and exporter tests: RIS, MEDLINE .nbib and CSV inputs, multi-line abstracts, missing fields, RIS round trip."""

import tempfile
import unittest
from pathlib import Path

from jev_screen.records import Record, detect_format, load_records, parse_csv, parse_nbib, parse_ris, to_ris

RIS = """TY  - JOUR
ID  - R1
TI  - First title
AU  - Doe, J.
AU  - Roe, R.
PY  - 2021///
AB  - First line of abstract
continues here
and here.
DO  - 10.0000/r1
ER  - 

TY  - JOUR
T1  - Second title with T1 tag
N2  - Abstract stored in N2
Y1  - 2019/01/01
ER  - 

TY  - JOUR
TI  - Third record has no abstract
ER  - 
"""

NBIB = """PMID- 11111
DP  - 2020 Mar 4
TI  - A title that wraps
      onto the next line
AB  - Background: something.
      Methods: more text on a continuation line.
      Results: done.
AU  - Doe J
AU  - Roe R
LID - 10.0000/n1 [doi]

PMID- 22222
DP  - 2018
TI  - Second nbib title
AID - 10.0000/n2 [doi]
AID - S0000-0000(18)00000-0 [pii]

"""

CSV = """id,Title,abstract,year,doi
c1,CSV title,"Abstract with, comma
and newline",2022,10.0000/c1
,Untitled abstract only,Only abstract,,
c3,Third,,2020,
"""


class RisParserTest(unittest.TestCase):
    def test_multi_line_abstract_and_tags(self):
        records = parse_ris(RIS)
        self.assertEqual(len(records), 3)
        first = records[0]
        self.assertEqual(first.id, "R1")
        self.assertEqual(first.title, "First title")
        self.assertEqual(first.abstract, "First line of abstract continues here and here.")
        self.assertEqual(first.authors, ["Doe, J.", "Roe, R."])
        self.assertEqual(first.year, "2021")
        self.assertEqual(first.doi, "10.0000/r1")

    def test_alternative_tags_and_missing_fields(self):
        records = parse_ris(RIS)
        second, third = records[1], records[2]
        self.assertEqual(second.title, "Second title with T1 tag")
        self.assertEqual(second.abstract, "Abstract stored in N2")
        self.assertEqual(second.year, "2019")
        self.assertEqual(second.id, "ris-2")  # no ID and no DOI: positional fallback
        self.assertEqual(third.abstract, "")
        self.assertFalse(third.has_abstract())

    def test_round_trip(self):
        records = [
            Record(id="A1", title="Alpha", abstract="Alpha abstract.", authors=["One, A.", "Two, B."], year="2020", doi="10.1/a"),
            Record(id="A2", title="Beta", abstract="", authors=[], year="", doi=""),
        ]
        again = parse_ris(to_ris(records))
        self.assertEqual(again, records)

    def test_notes_are_exported_but_not_parsed_as_fields(self):
        text = to_ris([Record(id="A1", title="Alpha")], notes={"A1": "jev-screen decision=include"})
        self.assertIn("N1  - jev-screen decision=include", text)
        self.assertEqual(parse_ris(text)[0].title, "Alpha")


class NbibParserTest(unittest.TestCase):
    def test_continuation_lines_and_doi(self):
        records = parse_nbib(NBIB)
        self.assertEqual(len(records), 2)
        first = records[0]
        self.assertEqual(first.id, "11111")
        self.assertEqual(first.title, "A title that wraps onto the next line")
        self.assertEqual(first.abstract, "Background: something. Methods: more text on a continuation line. Results: done.")
        self.assertEqual(first.authors, ["Doe J", "Roe R"])
        self.assertEqual(first.year, "2020")
        self.assertEqual(first.doi, "10.0000/n1")
        second = records[1]
        self.assertEqual(second.doi, "10.0000/n2")
        self.assertEqual(second.abstract, "")


class CsvParserTest(unittest.TestCase):
    def test_columns_and_fallback_ids(self):
        records = parse_csv(CSV)
        self.assertEqual(len(records), 3)
        self.assertEqual(records[0].title, "CSV title")
        self.assertEqual(records[0].abstract, "Abstract with, comma and newline")
        self.assertEqual(records[0].year, "2022")
        self.assertEqual(records[1].id, "csv-2")
        self.assertEqual(records[2].abstract, "")

    def test_requires_title_or_abstract_column(self):
        with self.assertRaises(ValueError):
            parse_csv("id,year\n1,2020\n")


class DetectionTest(unittest.TestCase):
    def test_extension_and_sniffing(self):
        self.assertEqual(detect_format("x.ris", ""), "ris")
        self.assertEqual(detect_format("x.nbib", ""), "nbib")
        self.assertEqual(detect_format("x.csv", ""), "csv")
        self.assertEqual(detect_format("pubmed.txt", NBIB), "nbib")
        self.assertEqual(detect_format("export.txt", RIS), "ris")
        with self.assertRaises(ValueError):
            detect_format("what.txt", "nothing here")

    def test_load_records_from_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.nbib"
            path.write_text(NBIB, encoding="utf-8")
            self.assertEqual(len(load_records(path)), 2)


if __name__ == "__main__":
    unittest.main()
