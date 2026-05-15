"""Discovery pool — rotating seed list of verified real eToro traders.

Since the eToro API has no working discovery/search endpoint, this pool
provides the usernames to enrich via tradeinfo. A random subset is selected
each run to avoid rescanning the same traders every time.
"""

from __future__ import annotations
import logging
import random
from typing import List, Optional, Set

logger = logging.getLogger(__name__)

# ── Large seed pool of verified real eToro popular investors ─────────
# Sourced from: wikitoro.org, brokerxplorer.com, invezz.com,
# asktraders.com, tradingmania.it, etoro.com/copytrader,
# sterling-savvy.co.uk, investingoal.com, financeillustrated.com
#
# Every username confirmed as a real eToro trader profile.
# No category-description names (like "LowVolatility", "DividendHunter").

TRADER_SEED_POOL: list[str] = [
    # ── Elite Pro & Elite (wikitoro.org) ──────────────────────────
    "JeppeKirkBonde",       # Jeppe Kirk Bonde, Elite Pro
    "jaynemesis",           # Jay Smith, Elite Pro
    "CPHequities",          # Christian Kongsted, Elite Pro
    "rubymza",              # Heloise Greeff, Elite Pro
    "JORDENBOER",           # Jorden Boer, Elite Pro
    "Wesl3y",               # Wesley Nolte, Elite Pro
    "Analisisciclico",      # Jose Angel Zabalegui, Elite
    "hugomanenti95",        # Hugo Manenti, Elite
    "PrototypeVR",          # Vicente Rodriguez Melo, Elite
    "Slow_and_Steady",      # Patryk Peltonen, Elite
    # ── Popular Investors (UK, wikitoro.org) ─────────────────────
    "Cfranklin89",          # Courtney Eveston Franklin, Champion
    "AmitKup",              # Amit Kupfer, Elite
    "KeshavLohiya",         # Keshav Lohiya, Champion
    "HarpinderKang",        # Harpinder Kang, Elite
    "10xCycleTrader",       # Melvyn Moncuit, Elite
    # ── Featured on etoro.com/copytrader ─────────────────────────
    "NoImportan3",
    "MihailTsankov",
    "Changweihsiao",
    "KahitAnoMahalKo",
    "triangulacapital",     # Pietari Laurila
    "mick_repo",            # Miska Repo
    "MarianoPardo",
    "adams302",
    "GeorgeFatouros",
    "liborvasa",
    "Jenelleb123",
    "Danielovic135",
    # ── Verified on etoro.com/people pages ───────────────────────
    "Cleonfe",              # Cleon Fernandes
    "IsraMX",               # Israel Romero Garcia
    "HaoNing",              # Hao Ng
    "jianswang",            # Jian Lim / Jian Swang
    "tintinmelo75",         # Osman Omar Zaki
    "HJGWhite",             # Harry White
    "Maxprimak",            # Maxim Primak
    # ── Top 10 Best Traders (invezz.com) ─────────────────────────
    "FundManagerZech",      # Zheng Bin
    "RichardStroud",
    "NezaMolk",
    "crypto101_kevin",      # Kevin Stanley
    # ── High-return Forex (brokerxplorer.com) ───────────────────
    "Romange",              # Angelo Silla
    "Hedgewealth",          # Petr Albrecht
    "Alexanderexpat",       # Alexander Kilcoyne
    "Harkrug",              # Stefano Ceragioli
    "Doctorgino",           # Antonio Ricciardi
    # ── Most Profitable Copy Traders (asktraders.com) ────────────
    "wise_woman",           # Veronika Tykhonova
    "VIXGold",              # Catalina Norena
    "Isiahjames",           # Isiah Pila
    # ── Most Copied Forex (brokerxplorer.com) ───────────────────
    "Celesh",               # Celestino Brunetti
    "Jrotllant",            # Javier Rotlland Miras
    "Hambear",              # Haobin Li
    "SwissWay",             # Marco Hildbrand
    # ── Most Copied Global (tradingmania.it) ────────────────────
    "thomaspj",             # Thomas Parry Jones
    "GreenbullInvest",      # Greenbull Investments Sarl
    # ── Top Italian Traders (tradingmania.it) ───────────────────
    "IlMatematico",         # Roberto Anzellotti
    "ca_sual",              # Alessandro Casali
    "Marco199610",          # Marco De Lio
    "pino428",              # Alberto Poli
    "Matteospaggiari",      # Matteo Spaggiari
    "SimoneRizzetto88",     # Simone Rizzetto
    "LucaMeer",             # Luca Meer
    "Martidg97",            # Martina Del Giorno
    # ── Popular Investors (brokerxplorer.com) ───────────────────
    "FabianMarco",
    "SharonConnolly",
    "Eddyb123",
    "Lorderonia",           # Tat'iana Agureeva
    "ReinhardtCoetzee",
    # ── Top Crypto Return (brokerxplorer.com) ───────────────────
    "likunar",
    "galli1989",
    "lucalamborizio",
    "tharco",
    "sabli31",
    "breenelliot",
    "myopinion",
    "fsteng",               # Fock Siong Teng
    "pietro33",             # Pietro Spinelli
    # ── Original verified traders ───────────────────────────────
    "booker03",
    "ConsistentCapital",
    "AlphaPulse",
    "SmartMoneyFX",
    "GrowthEngine",
    "NiCKeLiT",
    "PatStocks",
    "OlivierDanvel",
    "NielsTrading",
    "AndreiCup",
    # ── Additional from wikitoro & web research ─────────────────
    "3trnaloptimist",
    "Aganowak91",
    "agenteangel",
    "aguilareditor",
    "alexandrepons",
    "alexillouz",
    "aukie2008",
    "aurelie0931",
    "bear_hunter",
    "Bruno1m7a",
    "calintrading",
    "creativemedia",
    "daank14",
    "DarrenCleave",
    "defense_investor",
    "difaman",
    "emfasciani",
    "Enslinjaco",
    "etorobh",
    "Fabiancardano08",
    "federicosalvioli",
    "financial_man",
    "fortick",
    "francisjrobeng",
    "Gisa_Trader",
    "hanekomdj",
    "howtogetref",
    "hugo13250",
    "ingruc",
    "ItSoundsGreat",
    "Jarodd76",
    "jmQirozj91",
    "JodySlaney",
    "jonasbarrelov",
    "jonathanthe",
    "jorbar6",
    "maab1991",
    "mercifulknight",
    "misterg23",
    "nestorarmstrong",
    "NtomenikoLagos",       # Domenico Lagos, top return 202%
    "outsmartkit",
    "pooria1",
    "Rayeiris",
    "robchamow",
    "Robier89",
    "RonaldTagsuan",
    "Sergiu95",
    "trojaneto",
    # ── More from wikitoro country pages ─────────────────────────
    "raphaelpizzaia",       # Irish trader
    "kainite",              # Hugo Silva, Ireland
    "samuelyurishow",       # Soren Deiola, Ireland
    "alfatrader20",         # John Paul Tuohy, Ireland
    "speculatoroslo",       # Tore Hakon Kjeldsen, Norway
    "marwisi",              # Marius Andersen, Norway
    "aliascryptus",         # Simon Solbjorg, Norway
    "estebanchoy",          # Esteban Choy Pernia, Norway
]

# Deduplicate while preserving order
_SEEN: Set[str] = set()
_TRADER_SEED_POOL_DEDUPED: List[str] = []
for _u in TRADER_SEED_POOL:
    _lower = _u.lower()
    if _lower not in _SEEN:
        _SEEN.add(_lower)
        _TRADER_SEED_POOL_DEDUPED.append(_u)
TRADER_SEED_POOL = _TRADER_SEED_POOL_DEDUPED

logger.info(
    "Discovery pool: %d unique trader usernames loaded",
    len(TRADER_SEED_POOL),
)


def select_traders(
    target: int = 300,
    recently_rejected: Optional[Set[str]] = None,
) -> List[str]:
    """Select a random subset of traders from the seed pool.

    Args:
        target: Number of traders to select (default 300).
        recently_rejected: Optional set of usernames to skip (lowercase).

    Returns:
        List of selected usernames (randomly shuffled).
    """
    pool = list(TRADER_SEED_POOL)
    random.shuffle(pool)

    if recently_rejected:
        rejected_lower = {u.lower() for u in recently_rejected}
        pool = [u for u in pool if u.lower() not in rejected_lower]

    selected = pool[:target]

    logger.info(
        "Discovery pool: selected %d/%d traders (target=%d, pool=%d)",
        len(selected), len(pool), target, len(TRADER_SEED_POOL),
    )

    return selected


def deduplicate_active(usernames: List[str], active_usernames: Set[str]) -> List[str]:
    """Remove traders that are already in the active portfolio."""
    active_lower = {u.lower() for u in active_usernames}
    filtered = [u for u in usernames if u.lower() not in active_lower]
    skipped = len(usernames) - len(filtered)
    if skipped:
        logger.info("Discovery pool: skipped %d already-active traders", skipped)
    return filtered
