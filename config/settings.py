"""Chapter 13: AI for Target Prediction and Mechanistic Elucidation.

Targeted PubMed discovery, not a systematic-review completeness claim. Search
queries are unfiltered by date by default. Document actual run dates and the
final manuscript search cut-off after running and reviewing the logs.
"""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'data'
NP = '("natural product"[Title/Abstract] OR "natural products"[Title/Abstract] OR "natural compound"[Title/Abstract] OR "natural compounds"[Title/Abstract] OR "food compound"[Title/Abstract] OR "food compounds"[Title/Abstract] OR phytochemical*[Title/Abstract] OR plant-derived[Title/Abstract] OR ginsenoside*[Title/Abstract] OR celastrol[Title/Abstract] OR nimbolide[Title/Abstract])'
AI = '("machine learning"[Title/Abstract] OR "deep learning"[Title/Abstract] OR "artificial intelligence"[Title/Abstract] OR computational[Title/Abstract] OR "in silico"[Title/Abstract])'
TARGET = '("target prediction"[Title/Abstract] OR "target identification"[Title/Abstract] OR "target fishing"[Title/Abstract] OR "drug target interaction"[Title/Abstract] OR "drug-target interaction"[Title/Abstract] OR "compound-protein"[Title/Abstract] OR "protein-ligand"[Title/Abstract])'

BROAD_DISCOVERY_STREAMS = {
    'BROAD_NP_AI_TARGETS': (
        f'{NP} AND {AI} AND {TARGET}',
        f'{NP} AND ("target identification"[Title/Abstract] OR "mechanism of action"[Title/Abstract]) AND (bioactivity[Title/Abstract] OR binding[Title/Abstract] OR experimental[Title/Abstract])',
        '"natural product"[Title/Abstract] AND ("target fishing"[Title/Abstract] OR "target prediction"[Title/Abstract])',
    ),
    'BROAD_COMPOUND_PROTEIN_LEARNING': (
        f'{AI} AND ("drug-target interaction"[Title/Abstract] OR "protein-ligand interaction"[Title/Abstract]) AND (generaliz*[Title/Abstract] OR interpret*[Title/Abstract] OR benchmark*[Title/Abstract])',
        '"drug target"[Title/Abstract] AND ("cold start"[Title/Abstract] OR "domain adaptation"[Title/Abstract] OR "temporal validation"[Title/Abstract])',
    ),
    'BROAD_PERTURBATION_CONTEXT': (
        '("connectivity map"[Title/Abstract] OR "perturbation transcriptomics"[Title/Abstract] OR "perturbation response"[Title/Abstract]) AND ("mechanism of action"[Title/Abstract] OR "target identification"[Title/Abstract])',
        '("multi-omics"[Title/Abstract] OR "molecular profiling"[Title/Abstract]) AND ("drug target"[Title/Abstract] OR "compound target"[Title/Abstract]) AND (integrat*[Title/Abstract] OR latent[Title/Abstract])',
    ),
    'BROAD_ASSAYS_CAUSAL_EVIDENCE': (
        f'{NP} AND ("target engagement"[Title/Abstract] OR chemoproteomic*[Title/Abstract] OR "covalent binding"[Title/Abstract] OR "functional validation"[Title/Abstract])',
        '("cellular thermal shift assay"[Title/Abstract] OR "drug affinity responsive target stability"[Title/Abstract]) AND (compound[Title/Abstract] OR drug[Title/Abstract])',
    ),
    'BROAD_MAJOR_REVIEWS': (
        f'{NP} AND ("target prediction"[Title/Abstract] OR "target identification"[Title/Abstract] OR chemoproteomic*[Title/Abstract]) AND review[Publication Type]',
        '("drug-target interaction prediction"[Title/Abstract] OR "target deconvolution"[Title/Abstract]) AND review[Publication Type]',
    ),
}

TARGETED_SEARCH_STREAMS = {
    'S2_1_TASKS_AND_LABELS': (
        f'{NP} AND ("binding affinity"[Title/Abstract] OR "activity prediction"[Title/Abstract] OR "target ranking"[Title/Abstract]) AND {AI}',
        '("drug target interaction"[Title/Abstract] OR "target prediction"[Title/Abstract]) AND ("negative sampling"[Title/Abstract] OR "unknown interactions"[Title/Abstract])',
    ),
    'S2_2_CHEMICAL_SIMILARITY_TRANSFER': (
        f'{NP} AND (fingerprint*[Title/Abstract] OR "chemical similarity"[Title/Abstract] OR "transfer learning"[Title/Abstract] OR ensemble[Title/Abstract]) AND (target[Title/Abstract])',
        '("STarFish"[Title/Abstract] OR "CTAPred"[Title/Abstract] OR "natural product target prediction"[Title/Abstract])',
    ),
    'S2_2_PAIRED_DTI_MODELS': (
        '("DrugBAN"[Title/Abstract] OR "AI-Bind"[Title/Abstract] OR "DeepDTA"[Title/Abstract] OR "MolTrans"[Title/Abstract])',
        '("drug target interaction"[Title/Abstract]) AND ("bilinear attention"[Title/Abstract] OR "cold start"[Title/Abstract] OR "inductive"[Title/Abstract])',
    ),
    'S2_3_PERTURBATION_AND_CONTEXT': (
        '("DeepTarget"[Title/Abstract] OR "DTI-Voodoo"[Title/Abstract] OR "Connectivity Map"[Title/Abstract])',
        '("drug perturbation"[Title/Abstract] OR "drug response"[Title/Abstract]) AND ("target inference"[Title/Abstract] OR "mechanism of action"[Title/Abstract])',
    ),
    'S2_3_MULTIOMICS_FUSION': (
        '("MOFA"[Title/Abstract] OR "multi-omics factor analysis"[Title/Abstract] OR "DrugCMF"[Title/Abstract])',
        '("multimodal"[Title/Abstract] OR "multiomics"[Title/Abstract]) AND ("drug-target"[Title/Abstract] OR "protein-ligand"[Title/Abstract]) AND (fusion[Title/Abstract] OR integration[Title/Abstract])',
    ),
    'S2_4_EXPLANATION_AND_CONTACTS': (
        '("drug-target interaction"[Title/Abstract] OR "protein ligand"[Title/Abstract]) AND (attention[Title/Abstract] OR explainab*[Title/Abstract] OR interpretability[Title/Abstract]) AND (residue*[Title/Abstract] OR binding[Title/Abstract])',
        '("CMA-DTI"[Title/Abstract] OR "attention is not explanation"[Title/Abstract])',
    ),
    'S2_5_BINDING_ENGAGEMENT_CHEMOPROTEOMICS': (
        '("CETSA"[Title/Abstract] OR "DARTS"[Title/Abstract] OR "LiP-Quant"[Title/Abstract] OR "CeTEAM"[Title/Abstract]) AND (drug[Title/Abstract] OR compound[Title/Abstract] OR ligand[Title/Abstract])',
        f'{NP} AND ("target engagement"[Title/Abstract] OR "affinity purification"[Title/Abstract] OR "activity-based protein profiling"[Title/Abstract] OR "mass spectrometry"[Title/Abstract])',
    ),
    'S3_1_CLAIM_PROVENANCE_AND_NEGATIVE': (
        '("target identification"[Title/Abstract] OR "drug target"[Title/Abstract]) AND ("experimental validation"[Title/Abstract] OR "negative results"[Title/Abstract] OR "false positives"[Title/Abstract])',
    ),
    'S3_2_EXTERNAL_AND_COLD_EVALUATION': (
        '("drug target prediction"[Title/Abstract] OR "drug-target interaction"[Title/Abstract]) AND ("cold start"[Title/Abstract] OR "external validation"[Title/Abstract] OR "prospective evaluation"[Title/Abstract] OR "shortcut learning"[Title/Abstract])',
        '("LI-DTI"[Title/Abstract] OR "PANACEA"[Title/Abstract] OR "ScopeDTI"[Title/Abstract])',
    ),
    'S3_3_BIOCHEMICAL_EXPERIMENTAL': (
        f'{NP} AND ("enzyme inhibition"[Title/Abstract] OR "microscale thermophoresis"[Title/Abstract] OR "surface plasmon resonance"[Title/Abstract] OR "binding assay"[Title/Abstract])',
        '("ginsenoside"[Title/Abstract] OR "5-methoxysalicylic acid"[Title/Abstract]) AND (kinase[Title/Abstract] OR "cyclooxygenase"[Title/Abstract] OR "binding"[Title/Abstract])',
    ),
    'S3_3_AI_ASSAY_FOLLOWUP': (
        '("natural compounds"[Title/Abstract] OR "food compounds"[Title/Abstract]) AND ("machine learning"[Title/Abstract] OR computational[Title/Abstract]) AND ("target similarity"[Title/Abstract] OR "target prediction"[Title/Abstract] OR "bioactivity"[Title/Abstract])',
        '("natural products"[Title/Abstract] OR phytochemical*[Title/Abstract]) AND ("experimental validation"[Title/Abstract] OR "binding assay"[Title/Abstract] OR "enzyme inhibition"[Title/Abstract]) AND ("target"[Title/Abstract] OR "prediction"[Title/Abstract])',
    ),
    'S3_4_FUNCTIONAL_MECHANISM': (
        f'{NP} AND (rescue[Title/Abstract] OR knockout[Title/Abstract] OR knockdown[Title/Abstract] OR "resistant mutant"[Title/Abstract]) AND (target[Title/Abstract] OR mechanism[Title/Abstract])',
        '(nimbolide[Title/Abstract] OR acevaltrate[Title/Abstract] OR eupalinolide[Title/Abstract] OR gaudichaudione[Title/Abstract]) AND (binding[Title/Abstract] OR mechanism[Title/Abstract])',
    ),
    'S3_5_DISCORDANT_AND_EXPLANATION': (
        '("target engagement"[Title/Abstract]) AND ("off-target"[Title/Abstract] OR "phenotype"[Title/Abstract] OR discordant[Title/Abstract])',
    ),
    'S4_3_ASSAY_CONFOUNDING': (
        f'{NP} AND ("assay interference"[Title/Abstract] OR aggregation[Title/Abstract] OR luciferase[Title/Abstract] OR "promiscuous inhibition"[Title/Abstract])',
        '("phenolic compounds"[Title/Abstract] OR isoflavonoid*[Title/Abstract]) AND (aggregat*[Title/Abstract] OR "luciferase inhibition"[Title/Abstract])',
    ),
    'S4_5_FUTURE_PROSPECTIVE': (
        '("drug target prediction"[Title/Abstract] OR "target fishing"[Title/Abstract]) AND ("blinded"[Title/Abstract] OR "temporal validation"[Title/Abstract] OR "prospective experiment"[Title/Abstract])',
    ),
}
SEARCH_PHASES = {'broad': BROAD_DISCOVERY_STREAMS, 'targeted': TARGETED_SEARCH_STREAMS, 'all': {**BROAD_DISCOVERY_STREAMS, **TARGETED_SEARCH_STREAMS}}

@dataclass(frozen=True)
class Settings:
    root: Path = ROOT
    data_dir: Path = DATA_DIR
    metadata_dir: Path = DATA_DIR / 'metadata'
    full_text_dir: Path = DATA_DIR / 'full_text'
    logs_dir: Path = DATA_DIR / 'logs'
    external_records_dir: Path = DATA_DIR / 'external_records'
    search_exports_dir: Path = DATA_DIR / 'search_exports'
    claims_dir: Path = DATA_DIR / 'claims'
    entrez_email: str = os.getenv('NCBI_EMAIL','')
    entrez_api_key: str = os.getenv('NCBI_API_KEY','')
    ncbi_tool: str = 'Chapter13_Literature_Pipeline'
    max_retries: int = 5
    retry_backoff_seconds: float = 2.0
    entrez_batch_size: int = 200
    pubmed_retmax: int = 100000
    pubmed_sort: str = 'relevance'
SETTINGS = Settings()
PUBMED_SEARCH_STREAMS = SEARCH_PHASES
