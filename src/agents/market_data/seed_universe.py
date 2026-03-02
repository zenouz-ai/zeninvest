"""Curated seed universe of well-known stocks with T212 ticker mapping.

These are liquid, actively traded equities that yfinance can reliably fetch.
Pre-populated with sector and approximate market cap tier to bootstrap the
screener before the instruments table is enriched from live data.

Format: (t212_ticker, yf_ticker, name, sector, cap_tier)
cap_tier: "large" = $10B+, "mid" = $2B-$10B, "small" = $300M-$2B
"""

SEED_UNIVERSE: list[tuple[str, str, str, str, str]] = [
    # --- Technology ---
    ("AAPL_US_EQ", "AAPL", "Apple Inc", "Technology", "large"),
    ("MSFT_US_EQ", "MSFT", "Microsoft Corp", "Technology", "large"),
    ("GOOGL_US_EQ", "GOOGL", "Alphabet Inc", "Technology", "large"),
    ("AMZN_US_EQ", "AMZN", "Amazon.com Inc", "Technology", "large"),
    ("NVDA_US_EQ", "NVDA", "NVIDIA Corp", "Technology", "large"),
    ("META_US_EQ", "META", "Meta Platforms Inc", "Technology", "large"),
    ("TSM_US_EQ", "TSM", "Taiwan Semiconductor", "Technology", "large"),
    ("AVGO_US_EQ", "AVGO", "Broadcom Inc", "Technology", "large"),
    ("ORCL_US_EQ", "ORCL", "Oracle Corp", "Technology", "large"),
    ("CRM_US_EQ", "CRM", "Salesforce Inc", "Technology", "large"),
    ("ADBE_US_EQ", "ADBE", "Adobe Inc", "Technology", "large"),
    ("CSCO_US_EQ", "CSCO", "Cisco Systems", "Technology", "large"),
    ("ACN_US_EQ", "ACN", "Accenture PLC", "Technology", "large"),
    ("INTC_US_EQ", "INTC", "Intel Corp", "Technology", "large"),
    ("AMD_US_EQ", "AMD", "Advanced Micro Devices", "Technology", "large"),
    ("QCOM_US_EQ", "QCOM", "Qualcomm Inc", "Technology", "large"),
    ("TXN_US_EQ", "TXN", "Texas Instruments", "Technology", "large"),
    ("NOW_US_EQ", "NOW", "ServiceNow Inc", "Technology", "large"),
    ("IBM_US_EQ", "IBM", "IBM Corp", "Technology", "large"),
    ("AMAT_US_EQ", "AMAT", "Applied Materials", "Technology", "large"),
    ("MU_US_EQ", "MU", "Micron Technology", "Technology", "large"),
    ("PANW_US_EQ", "PANW", "Palo Alto Networks", "Technology", "large"),
    ("SNPS_US_EQ", "SNPS", "Synopsys Inc", "Technology", "large"),
    ("PLTR_US_EQ", "PLTR", "Palantir Technologies", "Technology", "large"),
    ("SHOP_US_EQ", "SHOP", "Shopify Inc", "Technology", "large"),
    ("NET_US_EQ", "NET", "Cloudflare Inc", "Technology", "mid"),
    ("CRWD_US_EQ", "CRWD", "CrowdStrike Holdings", "Technology", "large"),

    # --- Financial Services ---
    ("JPM_US_EQ", "JPM", "JPMorgan Chase", "Financial Services", "large"),
    ("V_US_EQ", "V", "Visa Inc", "Financial Services", "large"),
    ("MA_US_EQ", "MA", "Mastercard Inc", "Financial Services", "large"),
    ("BAC_US_EQ", "BAC", "Bank of America", "Financial Services", "large"),
    ("WFC_US_EQ", "WFC", "Wells Fargo", "Financial Services", "large"),
    ("GS_US_EQ", "GS", "Goldman Sachs", "Financial Services", "large"),
    ("MS_US_EQ", "MS", "Morgan Stanley", "Financial Services", "large"),
    ("BLK_US_EQ", "BLK", "BlackRock Inc", "Financial Services", "large"),
    ("SCHW_US_EQ", "SCHW", "Charles Schwab", "Financial Services", "large"),
    ("AXP_US_EQ", "AXP", "American Express", "Financial Services", "large"),
    ("C_US_EQ", "C", "Citigroup Inc", "Financial Services", "large"),
    ("PYPL_US_EQ", "PYPL", "PayPal Holdings", "Financial Services", "large"),
    ("CB_US_EQ", "CB", "Chubb Limited", "Financial Services", "large"),
    ("CME_US_EQ", "CME", "CME Group", "Financial Services", "large"),
    ("ICE_US_EQ", "ICE", "Intercontinental Exchange", "Financial Services", "large"),
    ("SQ_US_EQ", "SQ", "Block Inc", "Financial Services", "mid"),

    # --- Healthcare ---
    ("UNH_US_EQ", "UNH", "UnitedHealth Group", "Healthcare", "large"),
    ("JNJ_US_EQ", "JNJ", "Johnson & Johnson", "Healthcare", "large"),
    ("LLY_US_EQ", "LLY", "Eli Lilly", "Healthcare", "large"),
    ("ABBV_US_EQ", "ABBV", "AbbVie Inc", "Healthcare", "large"),
    ("MRK_US_EQ", "MRK", "Merck & Co", "Healthcare", "large"),
    ("PFE_US_EQ", "PFE", "Pfizer Inc", "Healthcare", "large"),
    ("TMO_US_EQ", "TMO", "Thermo Fisher Scientific", "Healthcare", "large"),
    ("ABT_US_EQ", "ABT", "Abbott Laboratories", "Healthcare", "large"),
    ("DHR_US_EQ", "DHR", "Danaher Corp", "Healthcare", "large"),
    ("AMGN_US_EQ", "AMGN", "Amgen Inc", "Healthcare", "large"),
    ("BMY_US_EQ", "BMY", "Bristol-Myers Squibb", "Healthcare", "large"),
    ("GILD_US_EQ", "GILD", "Gilead Sciences", "Healthcare", "large"),
    ("ISRG_US_EQ", "ISRG", "Intuitive Surgical", "Healthcare", "large"),
    ("VRTX_US_EQ", "VRTX", "Vertex Pharmaceuticals", "Healthcare", "large"),
    ("MDT_US_EQ", "MDT", "Medtronic PLC", "Healthcare", "large"),
    ("REGN_US_EQ", "REGN", "Regeneron Pharmaceuticals", "Healthcare", "large"),
    ("SYK_US_EQ", "SYK", "Stryker Corp", "Healthcare", "large"),
    ("ZTS_US_EQ", "ZTS", "Zoetis Inc", "Healthcare", "large"),

    # --- Consumer Cyclical ---
    ("TSLA_US_EQ", "TSLA", "Tesla Inc", "Consumer Cyclical", "large"),
    ("HD_US_EQ", "HD", "Home Depot", "Consumer Cyclical", "large"),
    ("MCD_US_EQ", "MCD", "McDonald's Corp", "Consumer Cyclical", "large"),
    ("NKE_US_EQ", "NKE", "Nike Inc", "Consumer Cyclical", "large"),
    ("LOW_US_EQ", "LOW", "Lowe's Companies", "Consumer Cyclical", "large"),
    ("SBUX_US_EQ", "SBUX", "Starbucks Corp", "Consumer Cyclical", "large"),
    ("TJX_US_EQ", "TJX", "TJX Companies", "Consumer Cyclical", "large"),
    ("BKNG_US_EQ", "BKNG", "Booking Holdings", "Consumer Cyclical", "large"),
    ("CMG_US_EQ", "CMG", "Chipotle Mexican Grill", "Consumer Cyclical", "large"),
    ("ABNB_US_EQ", "ABNB", "Airbnb Inc", "Consumer Cyclical", "large"),
    ("ORLY_US_EQ", "ORLY", "O'Reilly Automotive", "Consumer Cyclical", "large"),
    ("ROST_US_EQ", "ROST", "Ross Stores", "Consumer Cyclical", "mid"),
    ("GM_US_EQ", "GM", "General Motors", "Consumer Cyclical", "mid"),
    ("F_US_EQ", "F", "Ford Motor", "Consumer Cyclical", "mid"),
    ("LULU_US_EQ", "LULU", "Lululemon Athletica", "Consumer Cyclical", "mid"),

    # --- Consumer Defensive ---
    ("PG_US_EQ", "PG", "Procter & Gamble", "Consumer Defensive", "large"),
    ("KO_US_EQ", "KO", "Coca-Cola Co", "Consumer Defensive", "large"),
    ("PEP_US_EQ", "PEP", "PepsiCo Inc", "Consumer Defensive", "large"),
    ("COST_US_EQ", "COST", "Costco Wholesale", "Consumer Defensive", "large"),
    ("WMT_US_EQ", "WMT", "Walmart Inc", "Consumer Defensive", "large"),
    ("PM_US_EQ", "PM", "Philip Morris International", "Consumer Defensive", "large"),
    ("MO_US_EQ", "MO", "Altria Group", "Consumer Defensive", "large"),
    ("CL_US_EQ", "CL", "Colgate-Palmolive", "Consumer Defensive", "large"),
    ("MDLZ_US_EQ", "MDLZ", "Mondelez International", "Consumer Defensive", "large"),
    ("KHC_US_EQ", "KHC", "Kraft Heinz", "Consumer Defensive", "mid"),

    # --- Industrials ---
    ("CAT_US_EQ", "CAT", "Caterpillar Inc", "Industrials", "large"),
    ("UNP_US_EQ", "UNP", "Union Pacific", "Industrials", "large"),
    ("HON_US_EQ", "HON", "Honeywell International", "Industrials", "large"),
    ("RTX_US_EQ", "RTX", "RTX Corp", "Industrials", "large"),
    ("BA_US_EQ", "BA", "Boeing Co", "Industrials", "large"),
    ("DE_US_EQ", "DE", "Deere & Co", "Industrials", "large"),
    ("LMT_US_EQ", "LMT", "Lockheed Martin", "Industrials", "large"),
    ("GE_US_EQ", "GE", "GE Aerospace", "Industrials", "large"),
    ("MMM_US_EQ", "MMM", "3M Company", "Industrials", "large"),
    ("UPS_US_EQ", "UPS", "United Parcel Service", "Industrials", "large"),
    ("WM_US_EQ", "WM", "Waste Management", "Industrials", "large"),
    ("ETN_US_EQ", "ETN", "Eaton Corp", "Industrials", "large"),
    ("GD_US_EQ", "GD", "General Dynamics", "Industrials", "large"),
    ("NOC_US_EQ", "NOC", "Northrop Grumman", "Industrials", "large"),
    ("FDX_US_EQ", "FDX", "FedEx Corp", "Industrials", "large"),

    # --- Energy ---
    ("XOM_US_EQ", "XOM", "Exxon Mobil", "Energy", "large"),
    ("CVX_US_EQ", "CVX", "Chevron Corp", "Energy", "large"),
    ("COP_US_EQ", "COP", "ConocoPhillips", "Energy", "large"),
    ("SLB_US_EQ", "SLB", "Schlumberger Ltd", "Energy", "large"),
    ("EOG_US_EQ", "EOG", "EOG Resources", "Energy", "large"),
    ("MPC_US_EQ", "MPC", "Marathon Petroleum", "Energy", "large"),
    ("PSX_US_EQ", "PSX", "Phillips 66", "Energy", "large"),
    ("VLO_US_EQ", "VLO", "Valero Energy", "Energy", "mid"),
    ("OXY_US_EQ", "OXY", "Occidental Petroleum", "Energy", "mid"),
    ("HAL_US_EQ", "HAL", "Halliburton Co", "Energy", "mid"),

    # --- Communication Services ---
    ("GOOG_US_EQ", "GOOG", "Alphabet Inc (C)", "Communication Services", "large"),
    ("NFLX_US_EQ", "NFLX", "Netflix Inc", "Communication Services", "large"),
    ("DIS_US_EQ", "DIS", "Walt Disney Co", "Communication Services", "large"),
    ("CMCSA_US_EQ", "CMCSA", "Comcast Corp", "Communication Services", "large"),
    ("T_US_EQ", "T", "AT&T Inc", "Communication Services", "large"),
    ("VZ_US_EQ", "VZ", "Verizon Communications", "Communication Services", "large"),
    ("TMUS_US_EQ", "TMUS", "T-Mobile US", "Communication Services", "large"),
    ("ATVI_US_EQ", "ATVI", "Activision Blizzard", "Communication Services", "large"),
    ("SPOT_US_EQ", "SPOT", "Spotify Technology", "Communication Services", "large"),
    ("SNAP_US_EQ", "SNAP", "Snap Inc", "Communication Services", "mid"),
    ("PINS_US_EQ", "PINS", "Pinterest Inc", "Communication Services", "mid"),

    # --- Utilities ---
    ("NEE_US_EQ", "NEE", "NextEra Energy", "Utilities", "large"),
    ("DUK_US_EQ", "DUK", "Duke Energy", "Utilities", "large"),
    ("SO_US_EQ", "SO", "Southern Company", "Utilities", "large"),
    ("D_US_EQ", "D", "Dominion Energy", "Utilities", "large"),
    ("AEP_US_EQ", "AEP", "American Electric Power", "Utilities", "mid"),
    ("SRE_US_EQ", "SRE", "Sempra Energy", "Utilities", "mid"),
    ("EXC_US_EQ", "EXC", "Exelon Corp", "Utilities", "mid"),

    # --- Real Estate ---
    ("PLD_US_EQ", "PLD", "Prologis Inc", "Real Estate", "large"),
    ("AMT_US_EQ", "AMT", "American Tower", "Real Estate", "large"),
    ("CCI_US_EQ", "CCI", "Crown Castle Intl", "Real Estate", "large"),
    ("EQIX_US_EQ", "EQIX", "Equinix Inc", "Real Estate", "large"),
    ("SPG_US_EQ", "SPG", "Simon Property Group", "Real Estate", "mid"),
    ("O_US_EQ", "O", "Realty Income", "Real Estate", "mid"),
    ("WELL_US_EQ", "WELL", "Welltower Inc", "Real Estate", "mid"),

    # --- Materials ---
    ("LIN_US_EQ", "LIN", "Linde PLC", "Basic Materials", "large"),
    ("APD_US_EQ", "APD", "Air Products & Chemicals", "Basic Materials", "large"),
    ("SHW_US_EQ", "SHW", "Sherwin-Williams", "Basic Materials", "large"),
    ("ECL_US_EQ", "ECL", "Ecolab Inc", "Basic Materials", "large"),
    ("NEM_US_EQ", "NEM", "Newmont Corp", "Basic Materials", "large"),
    ("FCX_US_EQ", "FCX", "Freeport-McMoRan", "Basic Materials", "mid"),
    ("NUE_US_EQ", "NUE", "Nucor Corp", "Basic Materials", "mid"),
    ("DOW_US_EQ", "DOW", "Dow Inc", "Basic Materials", "mid"),
]

# Approximate market cap values for seeding (used only for initial population)
_CAP_VALUES = {
    "large": 50_000_000_000,   # $50B placeholder for large cap
    "mid": 5_000_000_000,      # $5B placeholder for mid cap
    "small": 1_000_000_000,    # $1B placeholder for small cap
}


def get_seed_instruments() -> list[dict]:
    """Return seed universe as list of dicts matching Instrument model fields."""
    return [
        {
            "ticker": t212,
            "yf_ticker": yf,
            "name": name,
            "sector": sector,
            "market_cap": _CAP_VALUES[cap_tier],
            "cap_tier": cap_tier,
        }
        for t212, yf, name, sector, cap_tier in SEED_UNIVERSE
    ]
