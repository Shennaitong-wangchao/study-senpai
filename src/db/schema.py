SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        platform TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        platform_message_id TEXT,
        sender_type TEXT NOT NULL,
        author_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        guild_id TEXT,
        reply_to_platform_message_id TEXT,
        thread_id TEXT,
        content TEXT NOT NULL,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        idempotency_claimed INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_messages_conversation_created_at ON messages(conversation_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_messages_user_created_at ON messages(user_id, created_at)",
    """
    CREATE TABLE IF NOT EXISTS session_memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        guild_id TEXT,
        memory_type TEXT NOT NULL,
        content TEXT NOT NULL,
        priority REAL NOT NULL DEFAULT 0.5,
        confidence REAL NOT NULL DEFAULT 0.5,
        status TEXT NOT NULL DEFAULT 'active',
        source_message_ids_json TEXT NOT NULL DEFAULT '[]',
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        last_active_at TEXT NOT NULL,
        expires_at TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_session_memories_scope ON session_memories(user_id, conversation_id, session_id, status)",
    """
    CREATE TABLE IF NOT EXISTS long_term_memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        memory_uid TEXT NOT NULL UNIQUE,
        user_id TEXT NOT NULL,
        conversation_id TEXT,
        channel_id TEXT,
        guild_id TEXT,
        memory_type TEXT NOT NULL,
        category TEXT NOT NULL,
        content TEXT NOT NULL,
        tags_json TEXT NOT NULL DEFAULT '[]',
        source_message_ids_json TEXT NOT NULL DEFAULT '[]',
        confidence REAL NOT NULL DEFAULT 0.5,
        importance REAL NOT NULL DEFAULT 0.5,
        status TEXT NOT NULL DEFAULT 'active',
        last_used_at TEXT,
        supersedes_memory_uid TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_long_term_memories_user_status ON long_term_memories(user_id, status, memory_type)",
    """
    CREATE TABLE IF NOT EXISTS structured_facts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        namespace TEXT NOT NULL,
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        confidence REAL NOT NULL DEFAULT 0.5,
        source_message_ids_json TEXT NOT NULL DEFAULT '[]',
        status TEXT NOT NULL DEFAULT 'active',
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(user_id, namespace, key)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_structured_facts_user_namespace ON structured_facts(user_id, namespace, status)",
    """
    CREATE TABLE IF NOT EXISTS relationship_states (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        dimension TEXT NOT NULL,
        value TEXT NOT NULL,
        weight REAL NOT NULL DEFAULT 0.5,
        confidence REAL NOT NULL DEFAULT 0.5,
        note TEXT,
        source_message_ids_json TEXT NOT NULL DEFAULT '[]',
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(user_id, dimension)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_relationship_states_user ON relationship_states(user_id, dimension)",
    """
    CREATE TABLE IF NOT EXISTS conversation_summaries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT NOT NULL,
        user_id TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        guild_id TEXT,
        session_id TEXT,
        summary_kind TEXT NOT NULL DEFAULT 'rolling',
        content TEXT NOT NULL,
        message_start_id INTEGER NOT NULL,
        message_end_id INTEGER NOT NULL,
        message_count INTEGER NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_conversation_summaries_scope ON conversation_summaries(conversation_id, message_end_id DESC)",
    """
    CREATE TABLE IF NOT EXISTS candidate_memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        candidate_uid TEXT NOT NULL UNIQUE,
        user_id TEXT NOT NULL,
        conversation_id TEXT,
        session_id TEXT,
        channel_id TEXT,
        guild_id TEXT,
        memory_type TEXT NOT NULL,
        category TEXT NOT NULL,
        content TEXT NOT NULL,
        tags_json TEXT NOT NULL DEFAULT '[]',
        confidence REAL NOT NULL DEFAULT 0.5,
        importance REAL NOT NULL DEFAULT 0.5,
        reason TEXT,
        source_message_ids_json TEXT NOT NULL DEFAULT '[]',
        dedupe_signature TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        metadata_json TEXT NOT NULL DEFAULT '{}',
        approved_memory_uid TEXT,
        review_note TEXT,
        reviewed_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_candidate_memories_status ON candidate_memories(user_id, status, updated_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS background_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_uid TEXT NOT NULL UNIQUE,
        task_type TEXT NOT NULL,
        user_id TEXT,
        conversation_id TEXT,
        session_id TEXT,
        dedupe_key TEXT,
        payload_json TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 3,
        priority REAL NOT NULL DEFAULT 0.5,
        timeout_seconds INTEGER NOT NULL DEFAULT 180,
        available_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT,
        last_error TEXT,
        result_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_background_tasks_status ON background_tasks(status, available_at, priority DESC)",
    """
    CREATE TABLE IF NOT EXISTS mode_states (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        mode TEXT NOT NULL DEFAULT 'auto',
        learning_mode INTEGER NOT NULL DEFAULT 0,
        custom_model TEXT,
        backup_model TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL,
        UNIQUE(user_id, conversation_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS health_checks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        component TEXT NOT NULL,
        status TEXT NOT NULL,
        message TEXT NOT NULL,
        latency_ms REAL NOT NULL DEFAULT 0,
        details_json TEXT NOT NULL DEFAULT '{}',
        checked_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_health_checks_component ON health_checks(component, checked_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS memory_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_uid TEXT NOT NULL UNIQUE,
        user_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        turn_uid TEXT,
        snapshot_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_memory_snapshots_scope ON memory_snapshots(conversation_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS memory_usage_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        memory_uid TEXT NOT NULL UNIQUE,
        user_id TEXT NOT NULL,
        hit_count INTEGER NOT NULL DEFAULT 0,
        last_hit_at TEXT,
        last_context_type TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_memory_usage_stats_user ON memory_usage_stats(user_id, hit_count DESC)",
    """
    CREATE TABLE IF NOT EXISTS turn_traces (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        turn_uid TEXT NOT NULL UNIQUE,
        user_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        user_message_id INTEGER,
        assistant_message_id INTEGER,
        request_type TEXT NOT NULL DEFAULT 'chat',
        reply_goal TEXT NOT NULL DEFAULT '陪伴',
        scene TEXT NOT NULL DEFAULT '日常闲聊',
        mode_text TEXT NOT NULL DEFAULT 'auto',
        model_name TEXT,
        backup_model_name TEXT,
        fallback_used INTEGER NOT NULL DEFAULT 0,
        latency_ms REAL NOT NULL DEFAULT 0,
        user_input TEXT NOT NULL,
        assistant_reply TEXT NOT NULL,
        attachments_json TEXT NOT NULL DEFAULT '[]',
        search_context_json TEXT NOT NULL DEFAULT '[]',
        planning_json TEXT NOT NULL DEFAULT '{}',
        retrieval_json TEXT NOT NULL DEFAULT '{}',
        metrics_json TEXT NOT NULL DEFAULT '{}',
        error_text TEXT,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_turn_traces_scope ON turn_traces(conversation_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS experience_metric_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        turn_uid TEXT NOT NULL UNIQUE,
        persona_consistency REAL NOT NULL DEFAULT 0,
        memory_hit_quality REAL NOT NULL DEFAULT 0,
        memory_usage_rate REAL NOT NULL DEFAULT 0,
        proactive_acceptance REAL NOT NULL DEFAULT 0,
        repeated_comfort_rate REAL NOT NULL DEFAULT 0,
        over_explaining_rate REAL NOT NULL DEFAULT 0,
        tool_trace_leakage_rate REAL NOT NULL DEFAULT 0,
        proactive_cold_response_rate REAL NOT NULL DEFAULT 0,
        structure_type TEXT NOT NULL DEFAULT 'plain',
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_experience_metric_events_created ON experience_metric_events(created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS proactive_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        proactive_uid TEXT NOT NULL UNIQUE,
        user_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        trigger_type TEXT NOT NULL,
        opening_text TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'sent',
        accepted INTEGER,
        cold_response INTEGER,
        response_message_id INTEGER,
        response_latency_minutes REAL,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        sent_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_proactive_messages_scope ON proactive_messages(user_id, sent_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS error_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        error_uid TEXT NOT NULL UNIQUE,
        component TEXT NOT NULL,
        severity TEXT NOT NULL DEFAULT 'error',
        message TEXT NOT NULL,
        details_json TEXT NOT NULL DEFAULT '{}',
        related_task_uid TEXT,
        related_turn_uid TEXT,
        status TEXT NOT NULL DEFAULT 'open',
        created_at TEXT NOT NULL,
        resolved_at TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_error_events_status ON error_events(status, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS attachment_artifacts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        artifact_uid TEXT NOT NULL UNIQUE,
        platform_message_id TEXT,
        user_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        filename TEXT NOT NULL,
        content_type TEXT,
        artifact_type TEXT NOT NULL,
        extracted_text TEXT NOT NULL DEFAULT '',
        summary_text TEXT NOT NULL DEFAULT '',
        truncated INTEGER NOT NULL DEFAULT 0,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_attachment_artifacts_message ON attachment_artifacts(conversation_id, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS companion_day_routes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        route_uid TEXT NOT NULL UNIQUE,
        user_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        local_date TEXT NOT NULL,
        timezone TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        current_scene TEXT NOT NULL DEFAULT '',
        mood_label TEXT NOT NULL DEFAULT '',
        longing_level REAL NOT NULL DEFAULT 0.7,
        quiet_mode INTEGER NOT NULL DEFAULT 0,
        route_json TEXT NOT NULL DEFAULT '{}',
        metadata_json TEXT NOT NULL DEFAULT '{}',
        generated_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(user_id, conversation_id, local_date)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_companion_day_routes_scope ON companion_day_routes(user_id, conversation_id, local_date DESC)",
    """
    CREATE TABLE IF NOT EXISTS companion_day_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_uid TEXT NOT NULL UNIQUE,
        route_uid TEXT NOT NULL,
        user_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        channel_id TEXT,
        event_type TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'planned',
        content TEXT NOT NULL DEFAULT '',
        card_json TEXT NOT NULL DEFAULT '{}',
        response_expected INTEGER NOT NULL DEFAULT 1,
        expectation_level TEXT NOT NULL DEFAULT 'clear',
        scheduled_for TEXT,
        sent_at TEXT,
        response_deadline_at TEXT,
        responded_at TEXT,
        response_message_id INTEGER,
        follow_up_of_event_uid TEXT,
        follow_up_sent_at TEXT,
        feedback TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_companion_day_events_scope ON companion_day_events(user_id, conversation_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_companion_day_events_route ON companion_day_events(route_uid, created_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS shared_diary_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        diary_uid TEXT NOT NULL UNIQUE,
        user_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        route_uid TEXT,
        event_uid TEXT,
        local_date TEXT NOT NULL,
        entry_type TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        content TEXT NOT NULL,
        role_scope TEXT NOT NULL DEFAULT 'companion',
        source TEXT NOT NULL DEFAULT 'day_engine',
        importance REAL NOT NULL DEFAULT 0.5,
        tags_json TEXT NOT NULL DEFAULT '[]',
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_shared_diary_entries_scope ON shared_diary_entries(user_id, conversation_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_shared_diary_entries_date ON shared_diary_entries(user_id, local_date DESC)",
    """
    CREATE TABLE IF NOT EXISTS reality_context_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_uid TEXT NOT NULL UNIQUE,
        user_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        source_type TEXT NOT NULL,
        source_label TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'ok',
        payload_json TEXT NOT NULL DEFAULT '{}',
        summary_text TEXT NOT NULL DEFAULT '',
        valid_from TEXT,
        valid_until TEXT,
        fetched_at TEXT NOT NULL,
        error_text TEXT,
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_reality_context_snapshots_scope ON reality_context_snapshots(user_id, conversation_id, source_type, fetched_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS calendar_context_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_uid TEXT NOT NULL UNIQUE,
        user_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        source_uid TEXT NOT NULL,
        source_label TEXT NOT NULL DEFAULT '',
        external_uid TEXT,
        event_hash TEXT NOT NULL,
        title TEXT NOT NULL,
        start_at TEXT NOT NULL,
        end_at TEXT,
        timezone TEXT NOT NULL DEFAULT '',
        location TEXT NOT NULL DEFAULT '',
        is_all_day INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'active',
        metadata_json TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(user_id, conversation_id, source_uid, event_hash)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_calendar_context_events_scope ON calendar_context_events(user_id, conversation_id, start_at ASC)",
    "CREATE INDEX IF NOT EXISTS idx_calendar_context_events_source ON calendar_context_events(source_uid, status, start_at ASC)",
    """
    CREATE TABLE IF NOT EXISTS reality_source_audits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        audit_uid TEXT NOT NULL UNIQUE,
        user_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        source_type TEXT NOT NULL,
        action TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'ok',
        details_json TEXT NOT NULL DEFAULT '{}',
        error_text TEXT,
        created_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_reality_source_audits_scope ON reality_source_audits(user_id, conversation_id, created_at DESC)",
]
