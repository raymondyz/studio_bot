CREATE TABLE IF NOT EXISTS players (
  id          INTEGER PRIMARY KEY,
  discord_id  INTEGER NOT NULL UNIQUE,
  name        TEXT    NOT NULL,
  active      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
  joined_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE TABLE IF NOT EXISTS snipes (
  id          INTEGER PRIMARY KEY,
  message_id  INTEGER NOT NULL UNIQUE,
  sniper_id   INTEGER NOT NULL REFERENCES players(id),
  sniped_at   TEXT    NOT NULL,
  status      TEXT    NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'confirmed', 'voided'))
);

CREATE TABLE IF NOT EXISTS snipe_targets (
  snipe_id   INTEGER NOT NULL REFERENCES snipes(id) ON DELETE CASCADE,
  target_id  INTEGER NOT NULL REFERENCES players(id),
  PRIMARY KEY (snipe_id, target_id)
);

CREATE INDEX IF NOT EXISTS idx_snipe_targets_target ON snipe_targets(target_id);