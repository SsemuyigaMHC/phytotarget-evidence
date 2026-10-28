"""NCBI Entrez client wrappers.

This module remains responsible only for NCBI/PubMed access. Other licensed
bibliographic databases are deliberately handled through their own exports or
connectors so source-specific authentication and terms do not get mixed into
the PubMed client.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from Bio import Entrez, Medline

from config.settings import SETTINGS
from utilities.retry import retry


LOGGER = logging.getLogger(__name__)


def _validate_search_count(count: int, pmids: list[str], retmax: int, query: str) -> None:
    """Fail rather than misreport a truncated PubMed retrieval as complete."""
    if count > retmax or len(pmids) < count:
        raise RuntimeError(
            f"PubMed search incomplete: {count} matches but only {len(pmids)} IDs received "
            f"(limit={retmax}). Split/refine search by publication date before proceeding: {query}"
        )


class EntrezClient:
    """Typed wrapper around Biopython Entrez with retry support."""

    def __init__(self) -> None:
        if not SETTINGS.entrez_email:
            LOGGER.warning(
                "NCBI_EMAIL is not set. NCBI strongly recommends providing one."
            )
        Entrez.email = SETTINGS.entrez_email or "unknown@example.org"
        Entrez.api_key = SETTINGS.entrez_api_key or None
        Entrez.tool = SETTINGS.ncbi_tool

    @retry(
        attempts=SETTINGS.max_retries,
        backoff_seconds=SETTINGS.retry_backoff_seconds,
    )
    def search_pubmed(
        self,
        query: str,
        retmax: int | None = None,
        sort: str | None = None,
    ) -> list[str]:
        """Run a PubMed search and return PMIDs as strings.

        retmax and sort are configurable so the retrieval strategy can be
        audited/reproduced without editing source code.
        """
        # NCBI PubMed ESearch returns no more than 10,000 IDs even if retmax is higher.
        # Large queries must be split instead of silently treating the first IDs as all hits.
        effective_retmax = min(10_000, SETTINGS.pubmed_retmax if retmax is None else retmax)
        effective_sort = SETTINGS.pubmed_sort if sort is None else sort

        with Entrez.esearch(
            db="pubmed",
            term=query,
            retmax=effective_retmax,
            sort=effective_sort,
            retmode="xml",
        ) as handle:
            record = Entrez.read(handle)

        count = int(record.get("Count", 0))
        pmids = [str(pmid) for pmid in record.get("IdList", [])]
        _validate_search_count(count, pmids, effective_retmax, query)
        return pmids

    @retry(
        attempts=SETTINGS.max_retries,
        backoff_seconds=SETTINGS.retry_backoff_seconds,
    )
    def fetch_pubmed_medline(
        self,
        pmids: Iterable[str],
    ) -> list[dict[str, object]]:
        """Fetch PubMed records in MEDLINE format."""
        pmid_list = list(pmids)
        if not pmid_list:
            return []

        with Entrez.efetch(
            db="pubmed",
            id=",".join(pmid_list),
            rettype="medline",
            retmode="text",
        ) as handle:
            return list(Medline.parse(handle))

    @retry(
        attempts=SETTINGS.max_retries,
        backoff_seconds=SETTINGS.retry_backoff_seconds,
    )
    def fetch_pubmed_xml(self, pmids: Iterable[str]) -> dict[str, object]:
        """Fetch PubMed XML records for fields not exposed in MEDLINE."""
        pmid_list = list(pmids)
        if not pmid_list:
            return {}

        with Entrez.efetch(
            db="pubmed",
            id=",".join(pmid_list),
            retmode="xml",
        ) as handle:
            return Entrez.read(handle)

    @retry(
        attempts=SETTINGS.max_retries,
        backoff_seconds=SETTINGS.retry_backoff_seconds,
    )
    def elink(self, dbfrom: str, db: str, identifier: str) -> list[str]:
        """Return linked identifiers from one NCBI database to another."""
        with Entrez.elink(
            dbfrom=dbfrom,
            db=db,
            id=identifier,
            retmode="xml",
        ) as handle:
            records = Entrez.read(handle)

        linked: list[str] = []
        for record in records:
            for linkset in record.get("LinkSetDb", []):
                linked.extend(str(link["Id"]) for link in linkset.get("Link", []))
        return linked
