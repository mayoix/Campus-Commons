-- Performance indexes for hosted Supabase deployment.
-- These indexes reduce lookup latency for frequent resource, mission,
-- booking and session queries.

CREATE INDEX IF NOT EXISTS idx_bookings_resource_status
ON bookings(resource_id, status);

CREATE INDEX IF NOT EXISTS idx_bookings_mission_status
ON bookings(mission_id, status);

CREATE INDEX IF NOT EXISTS idx_missions_requester_status
ON missions(requester_org_id, status);

CREATE INDEX IF NOT EXISTS idx_resources_status_owner
ON resources(status, owner_org_id);

CREATE INDEX IF NOT EXISTS idx_user_sessions_session_id
ON user_sessions(session_id);
