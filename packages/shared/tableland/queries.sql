-- Representative read queries the frontend issues against the Tableland gateway.
-- (Table names get a {chainId}_{tableId} suffix in production; use the gateway's
--  alias/registry to resolve logical -> physical names.)

-- Open markets with their latest AI prediction, ordered for the market explorer.
SELECT m.market_id, m.question, m.category, m.ai_prob_bps,
       m.yes_pool, m.no_pool, p.prob_yes_bps, p.ci_low_bps, p.ci_high_bps
FROM markets m
LEFT JOIN predictions p ON p.market_id = m.market_id
WHERE m.status = 'OPEN'
  AND p.computed_at = (SELECT MAX(computed_at) FROM predictions WHERE market_id = m.market_id)
ORDER BY m.close_at ASC;

-- Confidence decomposition for a market's newest prediction.
SELECT c.source, c.score_bps
FROM confidence_scores c
JOIN predictions p ON p.id = c.prediction_id
WHERE p.market_id = :market_id
ORDER BY p.computed_at DESC
LIMIT 8;

-- A wallet's open exposure across markets.
SELECT pos.market_id, m.question, pos.side, pos.amount, pos.claimed
FROM positions pos
JOIN markets m ON m.market_id = pos.market_id
WHERE pos.account = :account
ORDER BY pos.created_at DESC;

-- Active governance proposals with live tallies.
SELECT proposal_id, title, for_votes, against_votes, abstain_votes, quorum_bps, closes_at
FROM governance_proposals
WHERE status = 'ACTIVE'
ORDER BY closes_at ASC;
