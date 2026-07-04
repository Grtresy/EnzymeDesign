ALTER TABLE agent_members ADD COLUMN nickname TEXT;
ALTER TABLE agent_members ADD COLUMN display_name TEXT;
ALTER TABLE agent_members ADD COLUMN handle TEXT;

UPDATE agent_members
SET
    nickname = COALESCE(NULLIF(name, ''), agent_id),
    display_name = COALESCE(NULLIF(name, ''), agent_id),
    handle = '@' || lower(
        replace(
            replace(
                replace(COALESCE(NULLIF(name, ''), agent_id), 'agent:', ''),
                ' ',
                '-'
            ),
            ':',
            '-'
        )
    )
WHERE nickname IS NULL OR display_name IS NULL OR handle IS NULL;

CREATE INDEX IF NOT EXISTS idx_agent_members_session_handle
ON agent_members(session_id, handle);
