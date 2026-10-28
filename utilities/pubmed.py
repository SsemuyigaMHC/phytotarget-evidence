"""Literature retrieval, provenance, cross-database deduplication, and PubMed metadata.

Stage 01 deliberately separates:
1. retrieval (maximize recall),
2. record consolidation/deduplication (one paper = one canonical record),
3. metadata enrichment,
4. downstream screening.

PubMed remains fully programmatic. Scopus/Embase/Web of Science are supported
through exported records so institutional/licensed access can be used without
scraping. Their source identity and original query/provenance are retained.
"""

from __future__ import annotations

import csv
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd
from tqdm import tqdm

from config.settings import SETTINGS
from utilities.ncbi import EntrezClient


LOGGER = logging.getLogger(__name__)


def chunked(items: list[str], size: int) -> list[list[str]]:
    """Split a list into fixed-size chunks."""
    if size <= 0:
        raise ValueError("Chunk size must be > 0.")
    return [items[index : index + size] for index in range(0, len(items), size)]


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple, set)):
        return "; ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _normalise_doi(value: Any) -> str:
    doi = _clean(value).lower()
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi)
    doi = doi.removeprefix("doi:")
    return doi.strip().rstrip(" .;,")


def _normalise_pmid(value: Any) -> str:
    return re.sub(r"\D", "", _clean(value))


def _normalise_title(value: Any) -> str:
    title = _clean(value).lower()
    title = re.sub(r"<[^>]+>", " ", title)
    title = re.sub(r"[^a-z0-9]+", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def _first_author(value: Any) -> str:
    raw = _clean(value)
    if not raw:
        return ""
    first = re.split(r";|\||\n", raw)[0].strip().lower()
    first = re.sub(r"[^a-z0-9 ]+", " ", first)
    return re.sub(r"\s+", " ", first).strip().split(" ")[0]


def _year(value: Any) -> str:
    match = re.search(r"(19|20)\d{2}", _clean(value))
    return match.group(0) if match else ""


def _canonical_keys(record: dict[str, Any]) -> list[str]:
    """Return deterministic identity keys from strongest to weaker evidence."""
    keys: list[str] = []
    doi = _normalise_doi(record.get("DOI"))
    pmid = _normalise_pmid(record.get("PMID"))
    pmcid = _clean(record.get("PMCID")).lower()
    title = _normalise_title(record.get("Title"))
    author = _first_author(record.get("Authors"))
    year = _year(record.get("Year"))

    if doi:
        keys.append(f"doi:{doi}")
    if pmid:
        keys.append(f"pmid:{pmid}")
    if pmcid:
        keys.append(f"pmcid:{pmcid}")
    if title and author and year:
        keys.append(f"tay:{title}|{author}|{year}")
    elif title:
        keys.append(f"title:{title}")
    return keys


def _merge_provenance(existing: dict[str, Any], incoming: dict[str, Any]) -> None:
    """Merge source/query/accession provenance without overwriting useful data."""
    for field in (
        "Source Databases",
        "Database Record IDs",
        "Originating Search Streams",
        "Originating Search Queries",
        "Retrieval Sources",
    ):
        values = []
        for record in (existing, incoming):
            value = _clean(record.get(field))
            if value:
                values.extend(part.strip() for part in value.split(";") if part.strip())
        existing[field] = "; ".join(dict.fromkeys(values))

    for key, value in incoming.items():
        if key not in existing or not _clean(existing.get(key)):
            if _clean(value):
                existing[key] = value


def _read_csv_or_tsv(path: Path) -> pd.DataFrame:
    sep = "\t" if path.suffix.lower() in {".tsv", ".txt"} else ","
    return pd.read_csv(path, sep=sep, dtype=str, keep_default_na=False)


def _parse_ris(path: Path) -> pd.DataFrame:
    """Minimal dependency-free RIS parser for common bibliographic exports."""
    records: list[dict[str, str]] = []
    current: dict[str, str] = {}

    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        match = re.match(r"^([A-Z0-9]{2})\s+-\s+(.*)$", line)
        if not match:
            continue
        tag, value = match.groups()

        if tag == "TY":
            current = {}
        elif tag == "ER":
            if current:
                records.append(current)
            current = {}
            continue

        mapping = {
            "TI": "Title",
            "T1": "Title",
            "DO": "DOI",
            "AN": "Database Record ID",
            "SN": "ISSN",
            "PY": "Year",
            "DA": "Year",
            "AU": "Authors",
            "A1": "Authors",
            "JO": "Journal",
            "JF": "Journal",
            "AB": "Abstract",
            "KW": "Keywords",
            "UR": "URL",
        }
        field = mapping.get(tag)
        if not field:
            continue

        if field == "Authors":
            current[field] = "; ".join(
                [current[field], value] if current.get(field) else [value]
            )
        elif field in current and current[field]:
            current[field] = f"{current[field]}; {value}"
        else:
            current[field] = value

    if current:
        records.append(current)
    return pd.DataFrame(records)


def _source_from_filename(path: Path) -> str:
    name = path.stem.lower()
    if "scopus" in name:
        return "Scopus"
    if "embase" in name:
        return "Embase"
    if "wos" in name or "webofscience" in name or "web_of_science" in name:
        return "Web of Science"
    if "cinahl" in name:
        return "CINAHL"
    return "External"


def _normalise_external_frame(frame: pd.DataFrame, source: str) -> list[dict[str, Any]]:
    """Map common RIS/CSV export column variants into TRACES record fields."""
    aliases = {
        "Title": ["Title", "title", "TI", "Article Title", "Document Title"],
        "DOI": ["DOI", "doi", "DI"],
        "PMID": ["PMID", "PubMed ID", "PubMedID"],
        "PMCID": ["PMCID", "PMCID ID"],
        "Authors": ["Authors", "Author", "AU", "Author(s)"],
        "Journal": ["Journal", "Source title", "Publication Name", "SO"],
        "Year": ["Year", "Publication Year", "PY"],
        "Abstract": ["Abstract", "Description", "AB"],
        "Keywords": ["Keywords", "Author Keywords", "Index Keywords", "KW"],
        "Database Record ID": [
            "Database Record ID", "EID", "Scopus ID", "Accession Number",
            "UT", "Web of Science ID", "Embase ID", "AN",
        ],
    }

    lower_map = {str(column).strip().lower(): column for column in frame.columns}

    def pick(names: list[str]) -> str:
        for name in names:
            column = lower_map.get(name.lower())
            if column is not None:
                return column
        return ""

    records: list[dict[str, Any]] = []
    for _, row in frame.fillna("").iterrows():
        record = {
            field: _clean(row.get(pick(names), ""))
            for field, names in aliases.items()
        }
        if not record["Title"] and not record["DOI"] and not record["PMID"]:
            continue
        record["Source Databases"] = source
        record["Database Record IDs"] = record["Database Record ID"]
        record["Retrieval Sources"] = source
        record["Originating Search Streams"] = ""
        record["Originating Search Queries"] = ""
        records.append(record)
    return records


def ingest_external_exports(
    external_dir: Path,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Ingest licensed-database exports without scraping.

    Supported: .ris, .csv, .tsv, .txt. Files should contain the database name
    in the filename when possible (e.g. Scopus_results.ris).
    """
    records: list[dict[str, Any]] = []
    failures: list[str] = []

    if not external_dir.exists():
        LOGGER.info("No external-record directory found: %s", external_dir)
        return records, failures

    paths = sorted(
        path for path in external_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".ris", ".csv", ".tsv", ".txt"}
    )

    for path in paths:
        source = _source_from_filename(path)
        try:
            if path.suffix.lower() == ".ris":
                frame = _parse_ris(path)
            else:
                frame = _read_csv_or_tsv(path)
            imported = _normalise_external_frame(frame, source)
            records.extend(imported)
            LOGGER.info("Imported %s records from %s (%s)", len(imported), path, source)
        except Exception as error:
            failures.append(f"{path.name}\t{error}")
            LOGGER.exception("External literature import failed: %s", path)

    return records, failures


def search_all_queries(
    search_streams: dict[str, tuple[str, ...]] | tuple[str, ...],
) -> tuple[dict[str, dict[str, set[str]]], list[str]]:
    """Run PubMed searches while retaining stream + query provenance."""
    client = EntrezClient()
    if isinstance(search_streams, tuple):
        search_streams = {"UNSPECIFIED": search_streams}

    stream_to_query_to_pmids: dict[str, dict[str, set[str]]] = {}
    failed: list[str] = []

    for stream, queries in search_streams.items():
        stream_to_query_to_pmids[stream] = {}
        for query in tqdm(queries, desc=f"PubMed | {stream}"):
            try:
                pmids = set(client.search_pubmed(query))
                stream_to_query_to_pmids[stream][query] = pmids
                LOGGER.info(
                    "PubMed | stream=%s | query_hits=%s | query=%s",
                    stream, len(pmids), query,
                )
            except Exception as error:
                failed.append(f"PubMed\t{stream}\t{query}\t{error}")
                LOGGER.exception("PubMed search failed: %s", query)

    return stream_to_query_to_pmids, failed


def build_literature_index(
    query_to_pmids: dict[str, dict[str, set[str]]] | dict[str, set[str]],
    source_database: str = "PubMed",
    base_records: pd.DataFrame | None = None,
    external_records: list[dict[str, Any]] | None = None,
) -> pd.DataFrame:
    """Build one canonical record per publication while retaining all provenance."""
    canonical: dict[str, dict[str, Any]] = {}
    key_to_canonical: dict[str, str] = {}
    counter = 0

    def add(record: dict[str, Any]) -> None:
        nonlocal counter
        keys = _canonical_keys(record)
        if not keys:
            return

        existing_id = next((key_to_canonical[k] for k in keys if k in key_to_canonical), None)

        if existing_id is None:
            counter += 1
            existing_id = f"CH13-RET-{counter:07d}"
            canonical[existing_id] = dict(record)
            canonical[existing_id]["Canonical Record ID"] = existing_id
        else:
            _merge_provenance(canonical[existing_id], record)

        for key in keys:
            key_to_canonical[key] = existing_id

    # PubMed results
    if base_records is not None:
        for record in base_records.to_dict("records"):
            add(record)

    # New PubMed stream structure
    if query_to_pmids:
        sample_value = next(iter(query_to_pmids.values()))
        if isinstance(sample_value, dict):
            for stream, queries in query_to_pmids.items():
                for query, pmids in queries.items():
                    for pmid in pmids:
                        add({
                            "PMID": pmid,
                            "Source Databases": source_database,
                            "Database Record IDs": pmid,
                            "Originating Search Streams": stream,
                            "Originating Search Queries": query,
                            "Retrieval Sources": source_database,
                        })
        else:
            # Backward-compatible flat mapping.
            for query, pmids in query_to_pmids.items():
                for pmid in pmids:
                    add({
                        "PMID": pmid,
                        "Source Databases": source_database,
                        "Database Record IDs": pmid,
                        "Originating Search Streams": "UNSPECIFIED",
                        "Originating Search Queries": query,
                        "Retrieval Sources": source_database,
                    })

    for record in external_records or []:
        add(record)

    rows = list(canonical.values())
    if not rows:
        return pd.DataFrame(
            columns=[
                "Canonical Record ID", "PMID", "DOI", "PMCID", "Title", "Authors",
                "Journal", "Year", "Source Databases", "Database Record IDs",
                "Originating Search Streams", "Originating Search Queries",
                "Retrieval Sources",
            ]
        )

    frame = pd.DataFrame(rows)
    frame["Source Database Count"] = frame["Source Databases"].fillna("").apply(
        lambda value: len([x for x in str(value).split(";") if x.strip()])
    )
    frame["Potential Cross-Database Duplicate"] = frame["Source Database Count"] > 1
    return frame.sort_values("Canonical Record ID").reset_index(drop=True)


# Backward-compatible function name used by older Stage 01 code.
def build_pmid_index(query_to_pmids: dict[str, set[str]]) -> pd.DataFrame:
    return build_literature_index(query_to_pmids)


def _join(value: Any) -> str:
    return _clean(value)


def _doi_from_record(record: dict[str, Any]) -> str:
    for aid in record.get("AID", []):
        text = _clean(aid)
        if "[doi]" in text.lower():
            return _normalise_doi(text.replace(" [doi]", ""))
    return ""


def _pmcid_from_record(record: dict[str, Any]) -> str:
    for aid in record.get("AID", []):
        text = _clean(aid)
        if "[pmc]" in text.lower():
            return text.replace(" [pmc]", "").strip()
    return ""


def normalize_medline_record(record: dict[str, Any]) -> dict[str, str]:
    """Convert a MEDLINE record to the project metadata schema."""
    return {
        "PMID": _join(record.get("PMID")),
        "DOI": _doi_from_record(record),
        "PMCID": _pmcid_from_record(record),
        "Title": _join(record.get("TI")),
        "Authors": _join(record.get("AU")),
        "Journal": _join(record.get("JT") or record.get("TA")),
        "Year": _join(record.get("DP", ""))[:4],
        "Volume": _join(record.get("VI")),
        "Issue": _join(record.get("IP")),
        "Pages": _join(record.get("PG")),
        "Publication Type": _join(record.get("PT")),
        "Language": _join(record.get("LA")),
        "Abstract": _join(record.get("AB")),
        "Keywords": _join(record.get("OT")),
        "MeSH Terms": _join(record.get("MH")),
        "Grant Support": _join(record.get("GR")),
        "Country": _join(record.get("PL")),
        "Publisher": _join(record.get("PUBM")),
        "Corresponding Author": _join(record.get("AD")),
    }


def retrieve_metadata(literature_index: pd.DataFrame) -> pd.DataFrame:
    """Enrich canonical records with PubMed metadata where a PMID exists."""
    if literature_index.empty:
        return literature_index.copy()

    result = literature_index.copy()
    result["PMID"] = result["PMID"].fillna("").astype(str).map(_normalise_pmid)
    pmids = [pmid for pmid in result["PMID"].tolist() if pmid]

    if not pmids:
        return result

    client = EntrezClient()
    rows: list[dict[str, str]] = []

    for batch in tqdm(chunked(pmids, SETTINGS.entrez_batch_size), desc="PubMed metadata"):
        medline_records = client.fetch_pubmed_medline(batch)
        xml_records = client.fetch_pubmed_xml(batch)

        pmcid_lookup: dict[str, str] = {}
        for article in xml_records.get("PubmedArticle", []):
            citation = article.get("MedlineCitation", {})
            pmid = str(citation.get("PMID", ""))
            for article_id in (
                article.get("PubmedData", {}).get("ArticleIdList", [])
            ):
                if article_id.attributes.get("IdType") == "pmc":
                    pmcid_lookup[pmid] = str(article_id)
                    break

        for record in medline_records:
            normalized = normalize_medline_record(record)
            normalized["PMCID"] = pmcid_lookup.get(
                normalized["PMID"], normalized.get("PMCID", "")
            )
            rows.append(normalized)

    if not rows:
        return result

    metadata = pd.DataFrame(rows).drop_duplicates("PMID")
    metadata = metadata.set_index("PMID")

    # Fill missing canonical-record fields from PubMed without discarding
    # richer metadata supplied by Scopus/Embase/Web of Science exports.
    for column in metadata.columns:
        if column not in result.columns:
            result[column] = ""
        pubmed_values = result["PMID"].map(metadata[column]).fillna("")
        mask = result[column].fillna("").astype(str).str.strip().eq("") & pubmed_values.astype(str).str.strip().ne("")
        result.loc[mask, column] = pubmed_values[mask]

    return result


def write_literature_outputs(
    metadata: pd.DataFrame,
    query_to_pmids: dict[str, dict[str, set[str]]],
    failed: list[str],
    output_dir: Path,
) -> None:
    """Write screening-ready retrieval outputs with complete provenance."""
    output_dir.mkdir(parents=True, exist_ok=True)

    metadata.to_excel(output_dir / "Literature_Retrieval_Results.xlsx", index=False)
    metadata.to_csv(output_dir / "Literature_Retrieval_Results.csv", index=False)

    # Human-readable search log.
    with (output_dir / "Search_Log.txt").open("w", encoding="utf-8") as handle:
        for stream, queries in query_to_pmids.items():
            for query, pmids in queries.items():
                handle.write(f"PubMed\t{stream}\t{len(pmids)}\t{query}\n")

    with (output_dir / "Failed_Searches.txt").open("w", encoding="utf-8") as handle:
        handle.write("\n".join(failed))

    duplicate_columns = [
        column for column in (
            "Canonical Record ID", "PMID", "DOI", "Title",
            "Source Databases", "Database Record IDs",
            "Originating Search Streams", "Originating Search Queries",
        ) if column in metadata.columns
    ]
    duplicates = metadata.loc[
        metadata.get("Potential Cross-Database Duplicate", pd.Series(False, index=metadata.index)),
        duplicate_columns,
    ]
    duplicates.to_csv(
        output_dir / "Cross_Database_Duplicates.csv",
        index=False,
    )

    # Retain a separate PMID-level query overlap report for auditability.
    rows: list[dict[str, Any]] = []
    for stream, queries in query_to_pmids.items():
        for query, pmids in queries.items():
            for pmid in pmids:
                rows.append({
                    "PMID": pmid,
                    "Search Stream": stream,
                    "Search Query": query,
                })
    if rows:
        pd.DataFrame(rows).sort_values(["PMID", "Search Stream"]).to_csv(
            output_dir / "PubMed_Search_Provenance.csv", index=False
        )


# Backward-compatible output function name.
def write_pubmed_outputs(
    metadata: pd.DataFrame,
    query_to_pmids: dict[str, set[str]],
    failed: list[str],
    output_dir: Path,
) -> None:
    write_literature_outputs(metadata, {"UNSPECIFIED": query_to_pmids}, failed, output_dir)
