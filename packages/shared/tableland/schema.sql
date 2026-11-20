-- OracleForge · Tableland relational schema
-- ----------------------------------------------------------------------------
-- Tableland creates one SQLite-compatible table per CREATE TABLE, suffixed with
-- {chainId}_{tableId} at mint time. The app reads via the Tableland gateway and
-- writes through the TablelandTables registry (gated to the indexer/relayer).
-- Immutable artifacts (full question text, model outputs, evidence, dispute
-- records) live on Arweave; the `*_arweave_tx` columns hold the pointer, keeping
-- on-chain/relational rows small and the heavy payload permanent + auditable.
-- ----------------------------------------------------------------------------

-- Markets ---------------------------------------------------------------------
CREATE TABLE markets (
    market_id      TEXT PRIMARY KEY,         -- 0x… keccak(question, closeAt, chainId)
    question       TEXT NOT NULL,
    question_hash  TEXT NOT NULL,            -- sha256 canonical (joins to off-chain)
    category       TEXT NOT NULL,            -- MACRO | CRYPTO | GEO | CLIMATE | ...
    status         TEXT NOT NULL DEFAULT 'OPEN',  -- OPEN|CLOSED|RESOLVED|INVALID
    ai_prob_bps    INTEGER NOT NULL,         -- 0..10000 initialized YES probability
    yes_pool       TEXT NOT NULL DEFAULT '0',-- uint256 as decimal string
    no_pool        TEXT NOT NULL DEFAULT '0',
    outcome        INTEGER,                  -- 1=YES 0=NO null=unresolved
    created_at     INTEGER NOT NULL,
    close_at       INTEGER NOT NULL,
    proposed_at    INTEGER DEFAULT 0,        -- outcome-proposal time; start of the dispute window (0 if none)
    arweave_tx     TEXT                      -- full spec + evidence bundle
);
CREATE INDEX idx_markets_status   ON markets (status);
CREATE INDEX idx_markets_category ON markets (category);
CREATE INDEX idx_markets_close    ON markets (close_at);

-- AI predictions (one row per forecast recomputation) -------------------------
CREATE TABLE predictions (
    id              INTEGER PRIMARY KEY,
    market_id       TEXT NOT NULL,
    model           TEXT NOT NULL,           -- e.g. forge-forecast-v4
    prob_yes_bps    INTEGER NOT NULL,
    ci_low_bps      INTEGER NOT NULL,        -- 95% confidence interval
    ci_high_bps     INTEGER NOT NULL,
    samples         INTEGER NOT NULL,        -- Monte Carlo n
    input_hash      TEXT NOT NULL,           -- ties result to inputs (reproducible)
    computed_at     INTEGER NOT NULL,
    cartesi_epoch   INTEGER,                 -- rollup epoch that produced it
    arweave_tx      TEXT                     -- full model output
);
CREATE INDEX idx_pred_market ON predictions (market_id);

-- Confidence decomposition (per source, per prediction) -----------------------
CREATE TABLE confidence_scores (
    id            INTEGER PRIMARY KEY,
    prediction_id INTEGER NOT NULL,
    source        TEXT NOT NULL,             -- macro | news | crypto | climate ...
    score_bps     INTEGER NOT NULL           -- 0..10000
);
CREATE INDEX idx_conf_pred ON confidence_scores (prediction_id);

-- User positions --------------------------------------------------------------
CREATE TABLE positions (
    id          INTEGER PRIMARY KEY,
    market_id   TEXT NOT NULL,
    account     TEXT NOT NULL,               -- 0x wallet
    side        INTEGER NOT NULL,            -- 1=YES 0=NO
    amount      TEXT NOT NULL,               -- uint256 decimal string
    claimed     INTEGER NOT NULL DEFAULT 0,
    tx_hash     TEXT NOT NULL,
    created_at  INTEGER NOT NULL
);
CREATE INDEX idx_pos_market  ON positions (market_id);
CREATE INDEX idx_pos_account ON positions (account);

-- Oracle reports (settlement evidence) ----------------------------------------
CREATE TABLE oracle_reports (
    id          INTEGER PRIMARY KEY,
    market_id   TEXT NOT NULL,
    feed        TEXT NOT NULL,               -- EUR/USD, ECON/CPI, FUNCTIONS/NOAA ...
    answer      TEXT NOT NULL,
    comparator  INTEGER NOT NULL,            -- 0 >=  | 1 <=
    threshold   TEXT NOT NULL,
    outcome     INTEGER NOT NULL,            -- 1=YES 0=NO
    round_id    TEXT,
    reported_at INTEGER NOT NULL,
    arweave_tx  TEXT
);
CREATE INDEX idx_oracle_market ON oracle_reports (market_id);

-- Governance proposals --------------------------------------------------------
CREATE TABLE governance_proposals (
    proposal_id TEXT PRIMARY KEY,            -- OFP-47
    title       TEXT NOT NULL,
    proposer    TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'ACTIVE', -- ACTIVE|PASSED|REJECTED|EXECUTED
    for_votes   TEXT NOT NULL DEFAULT '0',
    against_votes TEXT NOT NULL DEFAULT '0',
    abstain_votes TEXT NOT NULL DEFAULT '0',
    quorum_bps  INTEGER NOT NULL,
    opens_at    INTEGER NOT NULL,
    closes_at   INTEGER NOT NULL,
    arweave_tx  TEXT                         -- full proposal text + discussion
);

-- Simulation outputs (scenario explorer) --------------------------------------
CREATE TABLE simulations (
    id          INTEGER PRIMARY KEY,
    market_id   TEXT,
    kind        TEXT NOT NULL,               -- monte_carlo | scenario_tree | risk_map
    horizon_days INTEGER NOT NULL,
    summary     TEXT NOT NULL,
    cartesi_epoch INTEGER,
    arweave_tx  TEXT NOT NULL,               -- full simulation payload
    created_at  INTEGER NOT NULL
);
CREATE INDEX idx_sim_market ON simulations (market_id);
