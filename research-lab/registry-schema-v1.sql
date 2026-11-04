-- 统一实验登记 schema v1
-- 来源：MUSE 自主策略发现系统实施方案 v1.1 §6。
-- 规则：SQLite 为准；attempts / knowledge / audit_log 只追加，触发器禁止 UPDATE 与 DELETE；
-- 计数器（每周 3 假设 / 20 正式实验）由 registry.py 在事务内强制，本 schema 只定义结构。
-- 格式版本：registry-schema-v1。格式变更须用户批准 + 版本号升级，旧库不迁移重算。

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS rounds (
    round_id    TEXT PRIMARY KEY,          -- ROUND-YYYY-Www，自然周
    week_start  TEXT NOT NULL,             -- YYYY-MM-DD（周一）
    status      TEXT NOT NULL DEFAULT 'open',  -- open / closed / halted
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hypotheses (
    hypothesis_id        TEXT PRIMARY KEY,  -- HYP-YYYYMMDD-NN
    round_id             TEXT NOT NULL REFERENCES rounds(round_id),
    title                TEXT NOT NULL,
    mechanism            TEXT NOT NULL,
    distinction_statement TEXT NOT NULL,    -- 与已归档失败策略的实质区别
    fingerprint          TEXT NOT NULL,     -- sha256(机制+标的池+频率+入场哈希+出场哈希+成本版本)
    screen_scores_json   TEXT NOT NULL,     -- 五项各 0/1/2 分
    screen_total         INTEGER NOT NULL,
    builds_on            TEXT NOT NULL DEFAULT '',  -- 继承的知识条目 ID，逗号分隔
    differs_from         TEXT NOT NULL DEFAULT '',  -- 区别于的知识条目 ID，逗号分隔
    status               TEXT NOT NULL DEFAULT 'IDEA',  -- IDEA/SCREEN/SPEC/BUILD/TEST/VALIDATE/ARCHIVE/FORWARD_REQ
    created_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS experiments (
    experiment_id      TEXT PRIMARY KEY,   -- EXP-YYYYMMDD-NNN
    hypothesis_id      TEXT NOT NULL REFERENCES hypotheses(hypothesis_id),
    round_id           TEXT NOT NULL REFERENCES rounds(round_id),
    spec_hash          TEXT NOT NULL,
    code_hash          TEXT,               -- BUILD 后填入
    snapshot_id        TEXT NOT NULL,
    cost_model_version TEXT NOT NULL,
    seed               INTEGER NOT NULL,
    status             TEXT NOT NULL DEFAULT 'SPEC',
    verdict            TEXT,               -- PASS / FAIL / INCONCLUSIVE
    created_at         TEXT NOT NULL,
    decided_at         TEXT
);

CREATE TABLE IF NOT EXISTS attempts (
    attempt_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_id TEXT NOT NULL REFERENCES experiments(experiment_id),
    kind         TEXT NOT NULL,             -- formal / reproduction
    run_at       TEXT NOT NULL,
    result_hash  TEXT,
    n_trades     INTEGER,
    mean_net_R   REAL,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS multiplicity (
    round_id           TEXT PRIMARY KEY REFERENCES rounds(round_id),
    total_hypotheses   INTEGER NOT NULL DEFAULT 0,
    total_experiments  INTEGER NOT NULL DEFAULT 0,
    total_attempts     INTEGER NOT NULL DEFAULT 0,
    total_param_combos INTEGER NOT NULL DEFAULT 0,
    updated_at         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge (
    knowledge_id  TEXT PRIMARY KEY,        -- KNOW-YYYYMMDD-NNN
    kind          TEXT NOT NULL,           -- mechanism / failure_pattern / cost_fact / data_fact
    conclusion    TEXT NOT NULL,
    evidence_refs TEXT NOT NULL,           -- 实验/快照 ID，逗号分隔
    confidence    TEXT NOT NULL,           -- high / medium / low
    last_reviewed TEXT NOT NULL,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS budgets (
    round_id    TEXT NOT NULL REFERENCES rounds(round_id),
    metric      TEXT NOT NULL,             -- hypotheses / formal_experiments / codex_calls / cpu_seconds ...
    limit_value REAL NOT NULL,
    used_value  REAL NOT NULL DEFAULT 0,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (round_id, metric)
);

CREATE TABLE IF NOT EXISTS audit_log (
    log_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT NOT NULL,
    actor      TEXT NOT NULL,
    action     TEXT NOT NULL,
    result     TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_hyp_round ON hypotheses(round_id);
CREATE INDEX IF NOT EXISTS idx_exp_round ON experiments(round_id);
CREATE INDEX IF NOT EXISTS idx_attempt_exp ON attempts(experiment_id);
CREATE INDEX IF NOT EXISTS idx_hyp_fingerprint ON hypotheses(fingerprint);

-- 只追加门禁：禁止 UPDATE / DELETE attempts、knowledge、audit_log。
-- 更正只能追加新行（新 attempt / 新 knowledge 版本 / 新 audit 记录），不得改写历史。
CREATE TRIGGER IF NOT EXISTS trg_attempts_no_update
BEFORE UPDATE ON attempts BEGIN
    SELECT RAISE(ABORT, 'attempts is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_attempts_no_delete
BEFORE DELETE ON attempts BEGIN
    SELECT RAISE(ABORT, 'attempts is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_knowledge_no_update
BEFORE UPDATE ON knowledge BEGIN
    SELECT RAISE(ABORT, 'knowledge is append-only: add a new entry instead');
END;

CREATE TRIGGER IF NOT EXISTS trg_knowledge_no_delete
BEFORE DELETE ON knowledge BEGIN
    SELECT RAISE(ABORT, 'knowledge is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_audit_no_update
BEFORE UPDATE ON audit_log BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;

CREATE TRIGGER IF NOT EXISTS trg_audit_no_delete
BEFORE DELETE ON audit_log BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;
