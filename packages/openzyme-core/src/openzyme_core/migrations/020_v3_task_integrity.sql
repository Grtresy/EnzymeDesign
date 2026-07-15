PRAGMA foreign_keys = ON;

CREATE TRIGGER task_dependencies_validate_insert
BEFORE INSERT ON task_dependencies
BEGIN
    SELECT CASE
        WHEN (
            SELECT session_id FROM tasks WHERE task_id = NEW.task_id
        ) != (
            SELECT session_id FROM tasks WHERE task_id = NEW.blocked_by_task_id
        )
        THEN RAISE(ABORT, 'task_dependency_cross_session')
    END;
    SELECT CASE WHEN EXISTS (
        WITH RECURSIVE dependency_ancestors(task_id) AS (
            SELECT NEW.blocked_by_task_id
            UNION
            SELECT dependency.blocked_by_task_id
            FROM task_dependencies AS dependency
            JOIN dependency_ancestors AS ancestor
              ON dependency.task_id = ancestor.task_id
        )
        SELECT 1
        FROM dependency_ancestors
        WHERE task_id = NEW.task_id
    ) THEN RAISE(ABORT, 'task_dependency_cycle') END;
END;

CREATE TRIGGER task_dependencies_validate_update
BEFORE UPDATE OF task_id, blocked_by_task_id ON task_dependencies
BEGIN
    SELECT CASE
        WHEN (
            SELECT session_id FROM tasks WHERE task_id = NEW.task_id
        ) != (
            SELECT session_id FROM tasks WHERE task_id = NEW.blocked_by_task_id
        )
        THEN RAISE(ABORT, 'task_dependency_cross_session')
    END;
    SELECT CASE WHEN EXISTS (
        WITH RECURSIVE dependency_ancestors(task_id) AS (
            SELECT NEW.blocked_by_task_id
            UNION
            SELECT dependency.blocked_by_task_id
            FROM task_dependencies AS dependency
            JOIN dependency_ancestors AS ancestor
              ON dependency.task_id = ancestor.task_id
            WHERE NOT (
                dependency.task_id = OLD.task_id
                AND dependency.blocked_by_task_id = OLD.blocked_by_task_id
            )
        )
        SELECT 1
        FROM dependency_ancestors
        WHERE task_id = NEW.task_id
    ) THEN RAISE(ABORT, 'task_dependency_cycle') END;
END;
