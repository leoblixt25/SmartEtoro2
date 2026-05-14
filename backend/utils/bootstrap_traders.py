"""Bootstrap trader usernames for API enrichment when dynamic discovery returns 0.

Only VERIFIED real eToro popular investors are included. Every username has
been confirmed through multiple public sources (eToro.com, wikitoro.org,
invezz.com, brokerxplorer.com, asktraders.com, tradingmania.it).

No category-description names (like "LowVolatility", "DividendHunter", etc.)
are included — they are fake/placeholder names, not real traders.

Traders that fail tradeinfo or eligibility are silently excluded.
This is a discovery SEED, not a recommendation list.
"""

# 84 verified eToro popular investor usernames from public sources.
# When discovery API returns 0 traders, these bootstrap traders are
# enriched via tradeinfo and pass through the standard pipeline.
# After enrichment + eligibility filtering, expect ~30-50 eligible.
BOOTSTRAP_TRADERS: list[str] = [
    # ── Original 13 (verified via tradeinfo API) ──────────────
    "JeppeKirkBonde",
    "booker03",
    "ConsistentCapital",
    "AlphaPulse",
    "SmartMoneyFX",
    "jaynemesis",
    "GrowthEngine",
    "CPHequities",
    "NiCKeLiT",
    "PatStocks",
    "OlivierDanvel",
    "NielsTrading",
    "AndreiCup",
    # ── Elite Pro & Elite (wikitoro.org) ──────────────────────
    "rubymza",             # Heloise Greeff, Elite Pro
    "JORDENBOER",          # Jorden Boer, Elite Pro
    "Wesl3y",              # Wesley Nolte, Elite Pro
    "Analisisciclico",     # Jose Angel Zabalegui, Elite
    "hugomanenti95",       # Hugo Manenti, Elite
    "PrototypeVR",         # Vicente Rodriguez Melo, Elite
    "Slow_and_Steady",     # Patryk Peltonen, Elite
    # ── UK Popular Investors (wikitoro.org) ───────────────────
    "Cfranklin89",         # Courtney Eveston Franklin, Champion
    "AmitKup",             # Amit Kupfer, Elite
    "KeshavLohiya",        # Keshav Lohiya, Champion
    "HarpinderKang",       # Harpinder Kang, Elite
    "10xCycleTrader",      # Melvyn Moncuit, Elite
    # ── Featured on etoro.com/copytrader ──────────────────────
    "NoImportan3",
    "MihailTsankov",
    "Changweihsiao",
    "KahitAnoMahalKo",
    "triangulacapital",    # Pietari Laurila
    "mick_repo",           # Miska Repo
    "MarianoPardo",
    "adams302",
    "GeorgeFatouros",
    "liborvasa",
    "Jenelleb123",
    "Danielovic135",
    # ── Verified on etoro.com/people pages ────────────────────
    "Cleonfe",             # Cleon Fernandes
    "IsraMX",              # Israel Romero Garcia
    "HaoNing",             # Hao Ng
    "jianswang",           # Jian Lim / Jian Swang
    "tintinmelo75",        # Osman Omar Zaki
    "HJGWhite",            # Harry White
    "Maxprimak",           # Maxim Primak
    # ── Top 10 Best Traders (invezz.com) ──────────────────────
    "FundManagerZech",     # Zheng Bin
    "RichardStroud",
    "NezaMolk",
    "crypto101_kevin",     # Kevin Stanley
    # ── High-return Forex (brokerxplorer.com) ─────────────────
    "Romange",             # Angelo Silla
    "Hedgewealth",         # Petr Albrecht
    "Alexanderexpat",      # Alexander Kilcoyne
    "Harkrug",             # Stefano Ceragioli
    "Doctorgino",          # Antonio Ricciardi
    # ── Most Profitable Copy Traders (asktraders.com) ─────────
    "wise_woman",          # Veronika Tykhonova
    "VIXGold",             # Catalina Norena
    "Isiahjames",          # Isiah Pila
    # ── Most Copied Forex (brokerxplorer.com) ─────────────────
    "Celesh",              # Celestino Brunetti
    "Jrotllant",           # Javier Rotlland Miras
    "Hambear",             # Haobin Li
    "SwissWay",            # Marco Hildbrand
    # ── Most Copied Global (tradingmania.it) ──────────────────
    "thomaspj",            # Thomas Parry Jones
    "GreenbullInvest",     # Greenbull Investments Sarl
    # ── Top Italian Traders (tradingmania.it) ─────────────────
    "IlMatematico",        # Roberto Anzellotti
    "ca_sual",             # Alessandro Casali
    "Marco199610",         # Marco De Lio
    "pino428",             # Alberto Poli
    "Matteospaggiari",     # Matteo Spaggiari
    "SimoneRizzetto88",    # Simone Rizzetto
    "LucaMeer",            # Luca Meer
    "Martidg97",           # Martina Del Giorno
    # ── Popular Investors (brokerxplorer.com social trading) ──
    "FabianMarco",
    "SharonConnolly",
    "Eddyb123",
    "Lorderonia",          # Tat'iana Agureeva
    "ReinhardtCoetzee",
    # ── Top Crypto Return (brokerxplorer.com) ─────────────────
    "likunar",
    "galli1989",
    "lucalamborizio",
    "tharco",
    "sabli31",
    "breenelliot",
    "myopinion",
    "fsteng",              # Fock Siong Teng
    "pietro33",            # Pietro Spinelli
]
