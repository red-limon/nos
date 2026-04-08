"""
Application factory pattern.
Creates and configures Flask application instance.
"""

import os

from flask import Flask
from nos.hooks import register_app_event_listeners

from .api import api_bp
from .config.loader import load_config
from .extensions import cors, db, socketio
from .services.errors import register_error_handlers
from .services.logging import configure_logging
from .sockets import register_socket_events
from .web import web_bp


def _migrate_instance_sqlite_filename(instance_folder: str) -> None:
    """
    If the legacy SQLite file exists and nos.db does not, rename orkestro.db -> nos.db.
    """
    import logging

    log = logging.getLogger(__name__)
    old = os.path.join(instance_folder, "orkestro.db")
    new = os.path.join(instance_folder, "nos.db")
    if os.path.isfile(old) and not os.path.isfile(new):
        try:
            os.replace(old, new)
            log.info("Renamed instance database orkestro.db -> nos.db")
        except OSError as exc:
            log.warning("Could not rename orkestro.db to nos.db: %s", exc)


def create_app(env: str | None = None) -> Flask:
    """
    Application factory.
    
    Args:
        env: Environment name (development, production). If None, reads from FLASK_ENV.
    
    Returns:
        Configured Flask application instance.
    """
    # Get the package directory (src/nos)
    package_dir = os.path.dirname(os.path.abspath(__file__))
    # Instance folder: src/instance (Flask convention for deployment-specific files)
    instance_folder = os.path.abspath(os.path.join(package_dir, "..", "instance"))
    os.makedirs(instance_folder, exist_ok=True)
    _migrate_instance_sqlite_filename(instance_folder)

    app = Flask(
        __name__,
        instance_path=instance_folder,
        instance_relative_config=True,
        template_folder=os.path.join(package_dir, "web", "templates"),
        static_folder=os.path.join(package_dir, "web", "static"),
        static_url_path="/static"
    )

    # Load configuration
    config = load_config(env)
    app.config.from_object(config)

    import logging

    log = logging.getLogger(__name__)

    # Override database URI to use instance folder (Flask convention)
    if not os.getenv("DATABASE_URL"):
        db_file = os.path.join(instance_folder, "nos.db")
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{db_file}"
        log.info("Using database: %s", db_file)

    # Second database: plugin metadata (PluginDbModel) — never mixed with core platform tables.
    binds = dict(app.config.get("SQLALCHEMY_BINDS") or {})
    if os.getenv("PLUGINS_DATABASE_URL"):
        binds["plugins"] = os.environ["PLUGINS_DATABASE_URL"].strip()
    elif "plugins" not in binds:
        plugins_file = os.path.join(instance_folder, "plugins.db")
        binds["plugins"] = f"sqlite:///{plugins_file}"
    app.config["SQLALCHEMY_BINDS"] = binds
    log.info("Plugins metadata DB (bind 'plugins'): %s", app.config["SQLALCHEMY_BINDS"].get("plugins"))

    # Configure logging
    configure_logging(app)

    # Engine paths that need platform EventLog (room, persist_to_db, nested workflow realtime)
    # resolve via a registered factory — core stays free of implicit platform coupling.
    from .services.event_log_factory import register_default_event_log_factory

    register_default_event_log_factory()

    # Initialize extensions
    db.init_app(app)
    
    # Initialize CORS for REST API (preflight OPTIONS must return 200 with CORS headers)
    default_origins = "http://localhost:8080,http://127.0.0.1:8080,http://localhost:8081,http://127.0.0.1:8081,http://localhost:8082,http://127.0.0.1:8082,http://nos:8082"
    cors_origins = app.config.get("CORS_ORIGINS", default_origins)
    if isinstance(cors_origins, str):
        cors_origins = [o.strip() for o in cors_origins.split(",") if o.strip()] if cors_origins != "*" else "*"
    cors.init_app(
        app,
        origins=cors_origins,
        supports_credentials=True,
        allow_headers=["Content-Type", "Authorization", "Accept", "X-Requested-With"],
        expose_headers=["Content-Type"],
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    
    # Initialize SocketIO
    # When using Waitress, use threading mode to avoid blocking
    # When running directly, use gevent
    use_waitress = os.getenv("USE_WAITRESS", "true").lower() == "true"
    async_mode = "threading" if use_waitress else app.config.get("SOCKETIO_ASYNC_MODE", "gevent")
    
    socketio.init_app(
        app,
        cors_allowed_origins=app.config.get("CORS_ORIGINS", "*"),
        async_mode=async_mode,
        allow_upgrades=not use_waitress,  # Disable WebSocket upgrade with Waitress (only polling)
        ping_timeout=60,
        ping_interval=25,
    )

    # Register blueprints
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(web_bp)

    # Inject app_title into all templates (global brand name)
    @app.context_processor
    def inject_app_title():
        return {"app_title": "nOS"}

    # Add middleware to log all requests (for debugging SSE) - only log important paths
    @app.before_request
    def log_request_info():
        from flask import request
        import logging
        logger = logging.getLogger(__name__)
        # Only log SSE and API requests to avoid spam
        if request.path in ['/events', '/api/users'] or request.path.startswith('/socket.io/'):
            logger.debug("Request: %s %s", request.method, request.path)

    # Register SocketIO events
    register_socket_events(socketio)
    register_app_event_listeners(socketio)

    # Register error handlers
    register_error_handlers(app)

    # Create database tables (must be done before loading plugins)
    with app.app_context():
        # Import sqlalchemy models to ensure they're registered with SQLAlchemy
        from .services import sqlalchemy  # noqa: F401

        # TEMPORARILY COMMENTED OUT
        # _migrate_workflow_table(db)
        db.create_all()
        _migrate_registration_fields(db)
        _migrate_module_paths(db)
        _migrate_execution_tables(db)
        _migrate_plugins_data_from_core_to_plugins_bind(app, db)
        _migrate_plugins_table(db)
        
        # Preload temporary data: 100,000 fake workflows (node preload is commented out)
        # TEMPORARILY COMMENTED OUT
        # _preload_plugin_data()
        
        # TEMPORARILY COMMENTED OUT
        # Preload test_datagrid with 467,000 fake records
        # _preload_test_datagrid()
        
        # Load registry from DB only (no default plugins from plugins/old).
        # If you need default nodes/workflows back, uncomment the block below and
        # the sync_* calls so they are loaded from code and synced to DB at startup.
        from nos.platform.loader_db import load_workflow_plugins

        # DEFAULTS NODES / DEFAULTS WORKFLOWS — commented out so deleted DB records stay deleted.
        # from nos.core.engine.plugin_loader import _load_plugin_module
        # from nos.platform.loader_db import sync_registry_workflows_to_db, sync_registry_nodes_to_db
        # _DEFAULT_PLUGIN_MODULES = [
        #     "nos.plugins.old.if_then_workflow",
        #     "nos.plugins.old.loop_workflow",
        #     "nos.plugins.old.standalone_nodes",
        #     "nos.plugins.old.mapping_example",
        #     "nos.plugins.old.web_scraper",
        #     "nos.plugins.old.html_to_markdown",
        #     "nos.plugins.old.web_to_markdown",
        # ]
        # for mod in _DEFAULT_PLUGIN_MODULES:
        #     _load_plugin_module(mod)
        # sync_registry_workflows_to_db()
        # sync_registry_nodes_to_db()

        load_workflow_plugins()

        from nos.platform.plugins import PluginManager

        PluginManager(app).load_and_enable_all()

    return app


def _migrate_registration_fields(db):
    """
    Migrate node and workflow tables: remove version, rename status -> registration_status (values OK/Error), add registration_date.
    Idempotent; safe to run on already-migrated or new DBs.
    """
    import logging
    from sqlalchemy import text, inspect

    logger = logging.getLogger(__name__)
    if db.engine.dialect.name != "sqlite":
        logger.info("Migration registration fields: skip (not SQLite)")
        return
    try:
        insp = inspect(db.engine)
        for table_name in ("workflow", "node", "assistant"):
            if table_name not in insp.get_table_names():
                continue
            with db.engine.connect() as conn:
                cols = [c["name"] for c in insp.get_columns(table_name)]
                if "registration_status" not in cols and "status" in cols:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN registration_status VARCHAR(20) DEFAULT 'Error'"))
                    conn.commit()
                    conn.execute(text(f"UPDATE {table_name} SET registration_status = CASE WHEN status = 'registered' THEN 'OK' ELSE 'Error' END"))
                    conn.commit()
                    conn.execute(text(f"ALTER TABLE {table_name} DROP COLUMN status"))
                    conn.commit()
                    logger.info("Migration: %s: status -> registration_status (OK/Error)", table_name)
                    insp = inspect(db.engine)
                    cols = [c["name"] for c in insp.get_columns(table_name)]
                if "registration_date" not in cols:
                    conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN registration_date DATETIME"))
                    conn.commit()
                    logger.info("Migration: %s: added registration_date", table_name)
                    insp = inspect(db.engine)
                    cols = [c["name"] for c in insp.get_columns(table_name)]
                if "version" in cols:
                    conn.execute(text(f"ALTER TABLE {table_name} DROP COLUMN version"))
                    conn.commit()
                    logger.info("Migration: %s: dropped version", table_name)
    except Exception as e:
        logger.warning("Migration registration fields: %s", e)


def _migrate_module_paths(db):
    """
    Migrate module_path in DB for older installs.

    Uses ``_LEGACY = "or" + "ke" + "stro"`` so the literal old package name is not stored
    as a contiguous substring (safe for future refactors).

    Order: project renames -> very old nested plugin paths -> remaining legacy prefix -> nos.
    Idempotent.
    """
    import logging
    from sqlalchemy import text

    logger = logging.getLogger(__name__)
    _LEGACY = "or" + "ke" + "stro"

    for table_name in ("workflow", "node", "assistant"):
        # hythera -> nos
        try:
            with db.engine.connect() as conn:
                sql = f"UPDATE {table_name} SET module_path = REPLACE(module_path, :old, :new) WHERE module_path LIKE :pattern"
                result = conn.execute(text(sql), {"old": "hythera", "new": "nos", "pattern": "hythera%"})
                conn.commit()
                if result.rowcount > 0:
                    logger.info(
                        "Migration module_path: %s: updated %d row(s) (hythera -> nos)",
                        table_name,
                        result.rowcount,
                    )
        except Exception as e:
            logger.warning("Migration module_path (hythera->nos): %s", e)

    for table_name in ("workflow", "node", "assistant"):
        # seedx_exp -> nos
        try:
            with db.engine.connect() as conn:
                sql = f"UPDATE {table_name} SET module_path = REPLACE(module_path, :old, :new) WHERE module_path LIKE :pattern"
                result = conn.execute(text(sql), {"old": "seedx_exp", "new": "nos", "pattern": "seedx_exp%"})
                conn.commit()
                if result.rowcount > 0:
                    logger.info(
                        "Migration module_path: %s: updated %d row(s) (seedx_exp -> nos)",
                        table_name,
                        result.rowcount,
                    )
        except Exception as e:
            logger.warning("Migration module_path (seedx_exp->nos): %s", e)

    # Legacy: <legacy>.core.workflows.plugins -> nos.plugins
    _wf_plugins = _LEGACY + ".core.workflows.plugins"
    try:
        for table_name in ("workflow", "node", "assistant"):
            with db.engine.connect() as conn:
                sql = f"UPDATE {table_name} SET module_path = REPLACE(module_path, :old, :new) WHERE module_path LIKE :pattern"
                result = conn.execute(
                    text(sql),
                    {"old": _wf_plugins, "new": "nos.plugins", "pattern": _wf_plugins + "%"},
                )
                conn.commit()
                if result.rowcount > 0:
                    logger.info(
                        "Migration module_path: %s: updated %d row(s) (legacy workflows.plugins -> nos.plugins)",
                        table_name,
                        result.rowcount,
                    )
    except Exception as e:
        logger.warning("Migration module_path (legacy workflows.plugins): %s", e)

    # Legacy: <legacy>.core.plugins -> nos.plugins
    _core_plugins = _LEGACY + ".core.plugins"
    try:
        for table_name in ("workflow", "node", "assistant"):
            with db.engine.connect() as conn:
                sql = f"UPDATE {table_name} SET module_path = REPLACE(module_path, :old, :new) WHERE module_path LIKE :pattern"
                result = conn.execute(
                    text(sql),
                    {"old": _core_plugins, "new": "nos.plugins", "pattern": _core_plugins + "%"},
                )
                conn.commit()
                if result.rowcount > 0:
                    logger.info(
                        "Migration module_path: %s: updated %d row(s) (legacy core.plugins -> nos.plugins)",
                        table_name,
                        result.rowcount,
                    )
    except Exception as e:
        logger.warning("Migration module_path (legacy core.plugins): %s", e)

    # Any remaining rows still using the old top-level package name (e.g. <legacy>.plugins.*)
    _legacy_dot = _LEGACY + "."
    try:
        for table_name in ("workflow", "node", "assistant"):
            with db.engine.connect() as conn:
                sql = f"UPDATE {table_name} SET module_path = REPLACE(module_path, :old, :new) WHERE module_path LIKE :pattern"
                result = conn.execute(
                    text(sql),
                    {"old": _legacy_dot, "new": "nos.", "pattern": _LEGACY + "%"},
                )
                conn.commit()
                if result.rowcount > 0:
                    logger.info(
                        "Migration module_path: %s: updated %d row(s) (legacy package prefix -> nos.)",
                        table_name,
                        result.rowcount,
                    )
    except Exception as e:
        logger.warning("Migration module_path (legacy package -> nos): %s", e)

    # plugins.X -> plugins.old.X — one-time historical migration; left commented.
    # try:
    #     prefix = "nos.plugins."
    #     prefix_old = "nos.plugins.old."
    #     ...
    # except Exception as e:
    #     logger.warning("Migration module_path (plugins.old): %s", e)


def _migrate_execution_tables(db):
    """
    Ensure execution_run table exists (created by db.create_all).
    Add ``pid`` column on legacy DBs (worker OS process id).
    Ensure ``execution_log(execution_id)`` is indexed for history queries.
    Idempotent; safe to run on already-migrated or new DBs.
    """
    import logging

    from sqlalchemy import inspect, text

    _logger = logging.getLogger(__name__)
    try:
        insp = inspect(db.engine)
        tables = insp.get_table_names()

        if "execution_run" in tables:
            _logger.info("Migration: execution_run table OK")
            cols = {c["name"] for c in insp.get_columns("execution_run")}
            if "pid" not in cols:
                with db.engine.begin() as conn:
                    conn.execute(text("ALTER TABLE execution_run ADD COLUMN pid INTEGER"))
                _logger.info("Migration: added execution_run.pid column")
        else:
            _logger.warning("Migration: execution_run table not found after db.create_all()")

        if "execution_log" in tables:
            try:
                with db.engine.begin() as conn:
                    conn.execute(
                        text(
                            "CREATE INDEX IF NOT EXISTS ix_execution_log_execution_id "
                            "ON execution_log (execution_id)"
                        )
                    )
                _logger.info("Migration: ensured ix_execution_log_execution_id index")
            except Exception as idx_exc:
                _logger.debug("Migration execution_log index (optional): %s", idx_exc)
    except Exception as e:
        _logger.warning("Migration execution tables: %s", e)


def _migrate_plugins_data_from_core_to_plugins_bind(app, db):
    """
    Legacy installs stored ``plugins`` on the core SQLite file. Copy rows into the ``plugins`` bind
    and drop the old table so metadata lives only in ``plugins.db`` (or PLUGINS_DATABASE_URL).
    """
    import logging
    from sqlalchemy import inspect, text

    from nos.platform.services.sqlalchemy.plugin.model import PluginDbModel

    logger = logging.getLogger(__name__)
    if (app.config.get("SQLALCHEMY_BINDS") or {}).get("plugins") is None:
        return
    try:
        core = db.engine
        plugins_eng = db.get_engine(bind="plugins")
    except Exception as exc:
        logger.warning("Migration plugins copy: could not get engines: %s", exc)
        return
    if core.dialect.name != "sqlite" or plugins_eng.dialect.name != "sqlite":
        return
    try:
        if "plugins" not in inspect(core).get_table_names():
            return
        if "plugins" not in inspect(plugins_eng).get_table_names():
            return
    except Exception as exc:
        logger.warning("Migration plugins copy: inspect failed: %s", exc)
        return

    with core.connect() as c1:
        n_core = c1.execute(text("SELECT COUNT(*) FROM plugins")).scalar()
    if not n_core:
        try:
            with core.begin() as conn:
                conn.execute(text("DROP TABLE IF EXISTS plugins"))
            logger.info("Migration: dropped empty legacy plugins table from core database")
        except Exception as exc:
            logger.warning("Migration: could not drop legacy plugins table: %s", exc)
        return

    with plugins_eng.connect() as c2:
        n_plug = c2.execute(text("SELECT COUNT(*) FROM plugins")).scalar()
    if n_plug:
        logger.info("Migration: plugins bind already has rows; skipping copy from core")
        return

    table = PluginDbModel.__table__
    cols = [c.name for c in table.columns]
    col_list = ", ".join(cols)
    placeholders = ", ".join(f":{c}" for c in cols)
    with core.connect() as src:
        rows = list(src.execute(text(f"SELECT {col_list} FROM plugins")).mappings().all())
    with plugins_eng.begin() as dst:
        for row in rows:
            dst.execute(text(f"INSERT INTO plugins ({col_list}) VALUES ({placeholders})"), dict(row))
    logger.info("Migration: copied %s plugin metadata row(s) from core DB to plugins bind", len(rows))
    try:
        with core.begin() as conn:
            conn.execute(text("DROP TABLE plugins"))
        logger.info("Migration: dropped legacy plugins table from core database")
    except Exception as exc:
        logger.warning("Migration: could not drop legacy plugins table after copy: %s", exc)


def _migrate_plugins_table(db):
    """
    Ensure ``plugins`` table exists on the **plugins** bind for entry-point metadata (PluginManager).
    """
    import logging
    from sqlalchemy import inspect

    _logger = logging.getLogger(__name__)
    try:
        plugins_eng = db.get_engine(bind="plugins")
        tables = inspect(plugins_eng).get_table_names()
        if "plugins" in tables:
            _logger.info("Migration: plugins table OK (plugins bind)")
        else:
            _logger.warning(
                "Migration: plugins table missing on plugins bind — importing model and create_all"
            )
            from nos.platform.services.sqlalchemy.plugin.model import PluginDbModel  # noqa: F401

            db.create_all()
    except Exception as e:
        _logger.warning("Migration plugins table: %s", e)


def _migrate_workflow_table(db):
    """Rename workflow_plugins -> workflow, drop id column if present. Idempotent. TEMPORARILY COMMENTED OUT (body below uses #)."""
    pass
    # from sqlalchemy import text, inspect
    # try:
    #     bind = db.engine
    #     insp = inspect(bind)
    #     tables = insp.get_table_names()
    #     if "workflow_plugins" in tables and "workflow" not in tables:
    #         with db.engine.connect() as conn:
    #             conn.execute(text("ALTER TABLE workflow_plugins RENAME TO workflow"))
    #             conn.commit()
    #     if "workflow" in insp.get_table_names():
    #         cols = [c["name"] for c in insp.get_columns("workflow")]
    #         if "id" in cols and bind.dialect.name == "sqlite":
    #             try:
    #                 with db.engine.connect() as conn:
    #                     conn.execute(text("ALTER TABLE workflow DROP COLUMN id"))
    #                     conn.commit()
    #             except Exception:
    #                 pass
    # except Exception as e:
    #     import logging
    #     logging.getLogger(__name__).warning("Migration workflow_plugins -> workflow: %s", e)


def _preload_plugin_data():
    """
    Preload 100,000 fake workflows for testing.
    Node preload is commented out.
    TEMPORARILY COMMENTED OUT (body below uses #).
    """
    pass
    # from .services.sqlalchemy import WorkflowDbModel, NodeDbModel
    # from .services.sqlalchemy import WorkflowStatus
    # import random
    # import logging
    #
    # logger = logging.getLogger(__name__)
    #
    # # Check if data already exists
    # existing_count = WorkflowDbModel.query.count()
    # if existing_count >= 100000:
    #     logger.info(f"Workflows already loaded: {existing_count}")
    #     return  # Data already loaded
    #
    # logger.info(f"Starting to generate 100,000 fake workflows (existing: {existing_count})...")
    #
    # # Generate 100,000 fake workflows
    # workflow_types = [
    #     ("data_processing", "DataProcessingWorkflow", "Data Processing"),
    #     ("analytics", "AnalyticsWorkflow", "Analytics"),
    #     ("etl", "ETLWorkflow", "ETL"),
    #     ("reporting", "ReportingWorkflow", "Reporting"),
    #     ("validation", "ValidationWorkflow", "Validation"),
    #     ("transformation", "TransformationWorkflow", "Transformation"),
    #     ("aggregation", "AggregationWorkflow", "Aggregation"),
    #     ("filtering", "FilteringWorkflow", "Filtering"),
    #     ("sorting", "SortingWorkflow", "Sorting"),
    #     ("mapping", "MappingWorkflow", "Mapping"),
    #     ("calculation", "CalculationWorkflow", "Calculation"),
    #     ("export", "ExportWorkflow", "Export"),
    #     ("import", "ImportWorkflow", "Import"),
    #     ("sync", "SyncWorkflow", "Synchronization"),
    #     ("backup", "BackupWorkflow", "Backup"),
    #     ("monitoring", "MonitoringWorkflow", "Monitoring"),
    #     ("alerting", "AlertingWorkflow", "Alerting"),
    #     ("scheduling", "SchedulingWorkflow", "Scheduling"),
    #     ("archiving", "ArchivingWorkflow", "Archiving"),
    #     ("cleaning", "CleaningWorkflow", "Cleaning"),
    # ]
    #
    # statuses = [WorkflowStatus.IN_PROGRESS, WorkflowStatus.TEST, WorkflowStatus.REGISTERED]
    # versioni = ["1.0.0", "1.1.0", "1.2.0", "2.0.0", "2.1.0", "3.0.0"]
    #
    # # Batch size for efficient insertion
    # BATCH_SIZE = 100
    # total_workflows = 10000
    # start_id = existing_count + 1
    #
    # # Generate workflows in batches
    # for batch_start in range(start_id, total_workflows + 1, BATCH_SIZE):
    #     batch_end = min(batch_start + BATCH_SIZE, total_workflows + 1)
    #     workflows = []
    #
    #     for i in range(batch_start, batch_end):
    #         workflow_type = random.choice(workflow_types)
    #         workflow_id = f"{workflow_type[0]}_{i:06d}"  # 6 digits for 100k+
    #         class_name = f"{workflow_type[1]}{i}"
    #         module_path = f"nos.plugins.{workflow_type[0]}_{i:06d}"
    #         name = f"{workflow_type[2]} Workflow {i}"
    #
    #         workflow = WorkflowDbModel(
    #             workflow_id=workflow_id,
    #             class_name=class_name,
    #             module_path=module_path,
    #             name=name,
    #             created_by="system",
    #             updated_by="system",
    #             status=random.choice(statuses).value,
    #             version=random.choice(versioni),
    #         )
    #         workflows.append(workflow)
    #
    #     # Add batch to session
    #     db.session.add_all(workflows)
    #     db.session.commit()
    #
    #     logger.info(f"Inserted workflows {batch_start} to {batch_end - 1} ({batch_end - batch_start} workflows)")
    #
    # logger.info(f"Successfully generated {total_workflows} fake workflows")
    #
    # # Preload 1 node: MultiplyNode
    # # TEMPORARILY COMMENTED OUT
    # # node = NodePlugin(
    # #     node_id="multiply",
    # #     class_name="MultiplyNode",
    # #     module_path="nos.plugins.standalone_nodes",
    # #     name="Multiply Node",
    # #     utente_creazione="system",
    # #     utente_aggiornamento="system",
    # #     stato_plugin=PluginStatus.VALIDO.value,
    # #     versione="1.0.0",
    # #     stato_registrazione=RegistrationStatus.REGISTERED.value
    # # )
    # # db.session.add(node)
    # # db.session.commit()


def _preload_test_datagrid():
    """
    Preload 467,000 fake records in test_datagrid table.
    TEMPORARILY COMMENTED OUT (body below uses #).
    """
    pass
    # from .services.sqlalchemy import TestDataGridDbModel
    # import random
    # from datetime import datetime, date, timedelta
    # import logging
    #
    # logger = logging.getLogger(__name__)
    #
    # # Check if data already exists
    # existing_count = TestDataGridDbModel.query.count()
    # if existing_count >= 467000:
    #     logger.info(f"TestDataGrid records already loaded: {existing_count}")
    #     return
    #
    # logger.info(f"Starting to generate 467,000 fake test_datagrid records (existing: {existing_count})...")
    #
    # # Data for fake generation
    # nomi = ["Mario", "Luigi", "Giuseppe", "Antonio", "Francesco", "Alessandro", "Lorenzo", "Mattia",
    #         "Leonardo", "Andrea", "Giovanni", "Marco", "Paolo", "Stefano", "Roberto", "Anna",
    #         "Maria", "Giulia", "Francesca", "Sara", "Chiara", "Valentina", "Martina", "Elena",
    #         "Alessandra", "Laura", "Silvia", "Federica", "Elisa", "Giorgia"]
    #
    # cognomi = ["Rossi", "Russo", "Ferrari", "Esposito", "Bianchi", "Romano", "Colombo", "Ricci",
    #            "Marino", "Greco", "Bruno", "Gallo", "Conti", "De Luca", "Costa", "Fontana",
    #            "Caruso", "Mancini", "Rizzo", "Lombardi", "Moretti", "Barbieri", "Ferrara",
    #            "Galli", "Martelli", "Leone", "Longo", "Gentile", "Martinelli", "Vitale"]
    #
    # paesi = ["Italia", "Francia", "Germania", "Spagna", "Regno Unito", "Stati Uniti", "Canada",
    #          "Australia", "Brasile", "Argentina", "Messico", "Giappone", "Cina", "India", "Russia"]
    #
    # stati_civili = ["celibe", "sposato", "divorziato", "vedovo"]
    # generi = ["maschio", "femmina", "altro"]
    #
    # # Batch size for efficient insertion
    # BATCH_SIZE = 100
    # total_records = 700
    # start_id = existing_count + 1
    #
    # # Generate records in batches
    # for batch_start in range(start_id, total_records + 1, BATCH_SIZE):
    #     batch_end = min(batch_start + BATCH_SIZE, total_records + 1)
    #     records = []
    #
    #     for i in range(batch_start, batch_end):
    #         nome = random.choice(nomi)
    #         cognome = random.choice(cognomi)
    #         email = f"{nome.lower()}.{cognome.lower()}.{i}@example.com"
    #         codice_fiscale = f"{random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}{random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}{random.randint(10000, 99999)}{random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}{random.randint(100, 999)}{random.choice('ABCDEFGHIJKLMNOPQRSTUVWXYZ')}"
    #
    #         # Random date of birth (18-80 years ago)
    #         years_ago = random.randint(18, 80)
    #         data_nascita = date.today() - timedelta(days=years_ago * 365 + random.randint(0, 365))
    #
    #         record = TestDataGridDbModel(
    #             nome=nome,
    #             cognome=cognome,
    #             codice_fiscale=codice_fiscale if random.random() > 0.1 else None,  # 90% have CF
    #             email=email,
    #             eta=random.randint(18, 80),
    #             reddito_annuo=random.randint(15000, 150000) if random.random() > 0.2 else None,
    #             telefono=f"+39 {random.randint(300, 399)} {random.randint(1000000, 9999999)}" if random.random() > 0.3 else None,
    #             sito_web=f"https://www.{nome.lower()}{cognome.lower()}.com" if random.random() > 0.7 else None,
    #             data_nascita=data_nascita if random.random() > 0.1 else None,
    #             stato_civile=random.choice(stati_civili) if random.random() > 0.1 else None,
    #             paese=random.choice(paesi) if random.random() > 0.1 else None,
    #             genere=random.choice(generi) if random.random() > 0.1 else None,
    #             newsletter=random.random() > 0.5,
    #             privacy_accettata=random.random() > 0.1,
    #             marketing=random.random() > 0.7,
    #             note=f"Note cliente {i}" if random.random() > 0.6 else None,
    #             indirizzo=f"Via {random.choice(['Roma', 'Milano', 'Napoli', 'Torino', 'Firenze'])} {random.randint(1, 200)}" if random.random() > 0.2 else None,
    #             colore_preferito=f"#{random.randint(0, 0xFFFFFF):06x}" if random.random() > 0.5 else None,
    #             livello_soddisfazione=random.randint(0, 100) if random.random() > 0.3 else None,
    #             documento_identita=f"/documents/id_{i}.pdf" if random.random() > 0.6 else None,
    #             codice_interno=f"INT-{i:06d}" if random.random() > 0.8 else None,
    #         )
    #         records.append(record)
    #
    #     # Add batch to session
    #     db.session.add_all(records)
    #     db.session.commit()
    #
    #     if batch_start % 10000 == 1 or batch_end == total_records + 1:
    #         logger.info(f"Inserted test_datagrid records {batch_start} to {batch_end - 1} ({batch_end - batch_start} records)")
    #
    # logger.info(f"Successfully generated {total_records} fake test_datagrid records")
