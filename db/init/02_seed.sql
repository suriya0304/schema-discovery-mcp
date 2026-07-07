-- Sample data: realistic, deterministic, enough volume for multi-table reasoning.

INSERT INTO squads (name, focus_area, formed_on) VALUES
    ('Prometheus',  'AI',       '2022-01-10'),
    ('Ironclad',    'Platform', '2021-06-01'),
    ('Lighthouse',  'Growth',   '2022-09-15'),
    ('Bastion',     'Security', '2023-02-20');

INSERT INTO contributors (full_name, email, title, seniority, squad_id, joined_on) VALUES
    ('Priya Raman',      'priya.raman@corp.io',      'ML Engineer',        'senior',    1, '2022-02-01'),
    ('Diego Alvarez',    'diego.alvarez@corp.io',     'Research Engineer', 'mid',       1, '2022-05-14'),
    ('Wei Chen',         'wei.chen@corp.io',          'ML Engineer',       'staff',     1, '2021-11-03'),
    ('Fatima Noor',      'fatima.noor@corp.io',       'Data Scientist',    'mid',       1, '2023-01-09'),
    ('Sam O''Neill',     'sam.oneill@corp.io',        'MLOps Engineer',    'junior',    1, '2023-08-21'),
    ('Grace Kim',        'grace.kim@corp.io',         'Backend Engineer',  'senior',    2, '2021-07-19'),
    ('Marcus Webb',      'marcus.webb@corp.io',       'Backend Engineer',  'mid',       2, '2022-03-11'),
    ('Anika Desai',      'anika.desai@corp.io',       'SRE',               'staff',     2, '2020-10-02'),
    ('Tom Baptiste',     'tom.baptiste@corp.io',      'Backend Engineer',  'junior',    2, '2024-01-15'),
    ('Elena Popescu',    'elena.popescu@corp.io',     'Growth PM',         'senior',    3, '2022-09-20'),
    ('Jonah Silver',     'jonah.silver@corp.io',      'Frontend Engineer', 'mid',       3, '2022-11-04'),
    ('Ravi Chandran',    'ravi.chandran@corp.io',     'Data Analyst',      'mid',       3, '2023-04-17'),
    ('Nadia Hussain',    'nadia.hussain@corp.io',     'Security Engineer', 'principal', 4, '2020-01-06'),
    ('Leo Fontaine',     'leo.fontaine@corp.io',      'Security Engineer', 'senior',    4, '2021-12-13'),
    ('Yuki Tanaka',      'yuki.tanaka@corp.io',       'Security Analyst',  'mid',       4, '2023-06-01'),
    ('Omar Sultan',      'omar.sultan@corp.io',       'Compliance Lead',   'staff',     4, '2022-07-25');

INSERT INTO initiatives (code, name, status, owning_squad_id, kicked_off_on) VALUES
    ('ATL-1', 'Atlas',    'active',  1, '2023-01-15'),
    ('NIM-2', 'Nimbus',   'active',  1, '2023-06-01'),
    ('HEL-3', 'Helios',   'planned', 2, '2024-02-10'),
    ('VOY-4', 'Voyager',  'shipped', 2, '2022-05-05'),
    ('SEN-5', 'Sentinel', 'active',  4, '2023-09-01'),
    ('COM-6', 'Comet',    'active',  3, '2023-11-11');

-- Tickets: mix of statuses/priorities across initiatives, reporters and assignees drawn from the owning squad (mostly).
INSERT INTO tickets (initiative_id, title, status, priority, reporter_id, assignee_id, opened_on, closed_on) VALUES
    (1, 'Model drift on fraud classifier',        'open',        'high',     2, 1,  '2024-03-01', NULL),
    (1, 'Add eval harness for prompt regression',  'in_progress', 'medium',   1, 3,  '2024-03-05', NULL),
    (1, 'Feature store latency spikes',            'open',        'critical', 3, 3,  '2024-04-02', NULL),
    (1, 'Retrain pipeline flaky on GPU node',       'blocked',     'high',     5, 5,  '2024-02-20', NULL),
    (1, 'Document embedding cache invalidation',    'closed',      'low',      4, 4,  '2024-01-10', '2024-01-25'),
    (2, 'Nimbus inference API 500s under load',     'open',        'critical', 3, 2,  '2024-04-10', NULL),
    (2, 'Add batching to Nimbus scoring service',   'in_progress', 'medium',   1, 1,  '2024-03-20', NULL),
    (2, 'Nimbus onboarding docs outdated',          'open',        'low',      4, NULL, '2024-04-01', NULL),
    (3, 'Design Helios service boundaries',         'in_progress', 'medium',   8, 6,  '2024-02-15', NULL),
    (3, 'Spike: Helios event bus choice',           'open',        'medium',   6, 7,  '2024-03-01', NULL),
    (4, 'Voyager post-launch cleanup',              'closed',      'low',      6, 9,  '2022-08-01', '2022-09-01'),
    (4, 'Voyager deprecate legacy endpoint',        'closed',      'medium',   8, 8,  '2023-01-10', '2023-02-01'),
    (5, 'Rotate compromised service creds',         'closed',      'critical', 13, 14, '2024-01-05', '2024-01-06'),
    (5, 'Pen-test findings remediation batch 3',    'open',        'high',     14, 15, '2024-04-05', NULL),
    (5, 'SOC2 evidence collection automation',      'in_progress', 'medium',   16, 13, '2024-03-15', NULL),
    (5, 'Sentinel alert fatigue tuning',             'open',        'medium',   15, 15, '2024-04-08', NULL),
    (5, 'Audit log tamper-proofing',                'blocked',     'high',     13, 16, '2024-02-01', NULL),
    (6, 'Comet onboarding funnel A/B test',          'open',        'medium',   10, 12, '2024-03-25', NULL),
    (6, 'Comet referral loop instrumentation',       'in_progress', 'medium',   11, 11, '2024-03-10', NULL),
    (6, 'Comet churn model handoff to Prometheus',   'open',        'high',     10, 1,  '2024-04-12', NULL),
    (2, 'Nimbus cost spike investigation',           'open',        'high',     3, NULL, '2024-04-15', NULL),
    (1, 'Atlas fairness audit follow-up',            'open',        'medium',   4, 2,  '2024-04-18', NULL);

INSERT INTO ticket_comments (ticket_id, author_id, body, created_at) VALUES
    (1, 1, 'Confirmed drift is concentrated in the EU segment, digging into feature distribution.', '2024-03-02 10:15:00'),
    (1, 3, 'Suspect the upstream feature pipeline backfill introduced skew last week.',              '2024-03-03 09:00:00'),
    (3, 3, 'Latency traced to a cold cache path on the feature store replica.',                       '2024-04-03 14:22:00'),
    (6, 2, 'Root cause looks like an unbounded batch size under burst traffic.',                       '2024-04-11 11:05:00'),
    (9, 6, 'Leaning towards an event-per-aggregate boundary, writing up an RFC.',                      '2024-02-18 16:40:00'),
    (14,15,'Two of five findings remediated, remaining three need infra changes.',                     '2024-04-06 08:30:00'),
    (17,13,'Blocked on legal sign-off for the retention policy change.',                               '2024-02-05 13:10:00'),
    (20,1, 'Prometheus can take this over next sprint once Nimbus batching lands.',                    '2024-04-13 09:45:00');

-- So list_tables' row-count estimates are accurate immediately instead of -1.
ANALYZE;
