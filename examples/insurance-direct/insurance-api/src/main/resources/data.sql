INSERT INTO policies (id, policy_number, holder_name, status, coverage_limit, created_at) VALUES
    ('b1c2e8d0-2222-4b3b-8d2b-000000000001', 'INS-2024-001', 'Alice Johnson', 'ACTIVE', 100000.00, NOW()),
    ('b1c2e8d0-2222-4b3b-8d2b-000000000002', 'INS-2024-002', 'Bob Smith', 'ACTIVE', 50000.00, NOW()),
    ('b1c2e8d0-2222-4b3b-8d2b-000000000003', 'INS-2024-003', 'Charlie Brown', 'INACTIVE', 75000.00, NOW())
ON CONFLICT (policy_number) DO NOTHING;
