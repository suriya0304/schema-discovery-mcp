-- Domain: internal product-engineering delivery tracker.
-- squads (teams) -> contributors (people) -> initiatives (projects) -> tickets (issues) -> ticket_comments
-- Deliberately five related tables so multi-hop JOIN reasoning is required.

CREATE TABLE squads (
    id           SERIAL PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    focus_area   TEXT NOT NULL,          -- e.g. 'AI', 'Platform', 'Growth', 'Security'
    formed_on    DATE NOT NULL
);

CREATE TABLE contributors (
    id           SERIAL PRIMARY KEY,
    full_name    TEXT NOT NULL,
    email        TEXT NOT NULL UNIQUE,
    title        TEXT NOT NULL,
    seniority    TEXT NOT NULL CHECK (seniority IN ('junior', 'mid', 'senior', 'staff', 'principal')),
    squad_id     INTEGER NOT NULL REFERENCES squads(id),
    joined_on    DATE NOT NULL
);

CREATE TABLE initiatives (
    id               SERIAL PRIMARY KEY,
    code             TEXT NOT NULL UNIQUE,
    name             TEXT NOT NULL UNIQUE,
    status           TEXT NOT NULL CHECK (status IN ('planned', 'active', 'paused', 'shipped')),
    owning_squad_id  INTEGER NOT NULL REFERENCES squads(id),
    kicked_off_on    DATE NOT NULL
);

CREATE TABLE tickets (
    id             SERIAL PRIMARY KEY,
    initiative_id  INTEGER NOT NULL REFERENCES initiatives(id),
    title          TEXT NOT NULL,
    status         TEXT NOT NULL CHECK (status IN ('open', 'in_progress', 'blocked', 'closed')),
    priority       TEXT NOT NULL CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    reporter_id    INTEGER NOT NULL REFERENCES contributors(id),
    assignee_id    INTEGER REFERENCES contributors(id),
    opened_on      DATE NOT NULL,
    closed_on      DATE
);

CREATE TABLE ticket_comments (
    id          SERIAL PRIMARY KEY,
    ticket_id   INTEGER NOT NULL REFERENCES tickets(id),
    author_id   INTEGER NOT NULL REFERENCES contributors(id),
    body        TEXT NOT NULL,
    created_at  TIMESTAMP NOT NULL
);

CREATE INDEX idx_contributors_squad ON contributors(squad_id);
CREATE INDEX idx_initiatives_squad ON initiatives(owning_squad_id);
CREATE INDEX idx_tickets_initiative ON tickets(initiative_id);
CREATE INDEX idx_tickets_assignee ON tickets(assignee_id);
CREATE INDEX idx_ticket_comments_ticket ON ticket_comments(ticket_id);
