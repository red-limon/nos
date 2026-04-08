"""
Plugin Management Service.

Provides business logic for managing node/workflow plugins:
- Registration/Unregistration
- Publishing/Unpublishing
- Update, Info, Reload
- File operations (delete, rename, copy)

Can be called from both REST API and Socket.IO handlers.
"""

import os
import shutil
import logging
from typing import Literal, Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

PluginType = Literal["node", "workflow"]


@dataclass
class PluginOperationResult:
    """Result of a plugin management operation."""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


# =============================================================================
# Helper Functions
# =============================================================================

def _get_repository(plugin_type: PluginType):
    """Get the appropriate repository for the plugin type."""
    if plugin_type == "node":
        from .sqlalchemy.node import repository as repo
        return repo
    elif plugin_type == "workflow":
        from .sqlalchemy.workflow import repository as repo
        return repo
    else:
        raise ValueError(f"Invalid plugin_type: {plugin_type}")


def _get_registry():
    """Get the workflow registry."""
    from nos.core.engine.registry import workflow_registry
    return workflow_registry


def _resolve_file_path(plugin_type: PluginType, module_path: str) -> Optional[str]:
    """Resolve module path to file system path."""
    from .plugin_code_service import resolve_node_path, resolve_workflow_path
    
    if plugin_type == "node":
        file_path, _ = resolve_node_path(module_path)
    else:
        file_path, _ = resolve_workflow_path(module_path)
    
    return file_path


# =============================================================================
# Unregister Plugin
# =============================================================================

def unregister_plugin(plugin_type: PluginType, plugin_id: str) -> PluginOperationResult:
    """
    Unregister a plugin (delete DB record).
    
    Only allowed if status is not 'Pub' (published).
    Also removes from in-memory registry.
    
    Args:
        plugin_type: "node" or "workflow"
        plugin_id: Plugin identifier
        
    Returns:
        PluginOperationResult
    """
    from .sqlalchemy.enums import RegistrationStatus
    from ..extensions import db
    
    repo = _get_repository(plugin_type)
    registry = _get_registry()
    
    # Get plugin from DB
    plugin = repo.get_by_id(plugin_id)
    if not plugin:
        return PluginOperationResult(
            success=False,
            message=f"{plugin_type.capitalize()} '{plugin_id}' not found in database"
        )
    
    # Check status - cannot unregister published plugins
    if plugin.registration_status == RegistrationStatus.PUBLISHED.value:
        return PluginOperationResult(
            success=False,
            message=f"Cannot unregister published {plugin_type}. Use 'unpub' first."
        )
    
    # Remove from in-memory registry
    if plugin_type == "node":
        registry.unregister_node(plugin_id)
    else:
        registry.unregister_workflow(plugin_id)
    
    # Delete from database
    try:
        db.session.delete(plugin)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to delete {plugin_type} from DB: {e}")
        return PluginOperationResult(
            success=False,
            message=f"Database error: {str(e)}"
        )
    
    return PluginOperationResult(
        success=True,
        message=f"{plugin_type.capitalize()} '{plugin_id}' unregistered successfully",
        data={"plugin_id": plugin_id, "plugin_type": plugin_type}
    )


# =============================================================================
# Publish / Unpublish Plugin
# =============================================================================

def publish_plugin(plugin_type: PluginType, plugin_id: str) -> PluginOperationResult:
    """
    Publish a plugin (change status from OK to Pub).
    
    Args:
        plugin_type: "node" or "workflow"
        plugin_id: Plugin identifier
        
    Returns:
        PluginOperationResult
    """
    from .sqlalchemy.enums import RegistrationStatus
    from ..extensions import db
    
    repo = _get_repository(plugin_type)
    
    # Get plugin from DB
    plugin = repo.get_by_id(plugin_id)
    if not plugin:
        return PluginOperationResult(
            success=False,
            message=f"{plugin_type.capitalize()} '{plugin_id}' not found in database"
        )
    
    # Check current status
    if plugin.registration_status == RegistrationStatus.PUBLISHED.value:
        return PluginOperationResult(
            success=False,
            message=f"{plugin_type.capitalize()} '{plugin_id}' is already published"
        )
    
    if plugin.registration_status != RegistrationStatus.OK.value:
        return PluginOperationResult(
            success=False,
            message=f"Cannot publish {plugin_type} with status '{plugin.registration_status}'. Must be 'OK'."
        )
    
    # Update status
    try:
        plugin.registration_status = RegistrationStatus.PUBLISHED.value
        plugin.updated_at = datetime.utcnow()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to publish {plugin_type}: {e}")
        return PluginOperationResult(
            success=False,
            message=f"Database error: {str(e)}"
        )
    
    return PluginOperationResult(
        success=True,
        message=f"{plugin_type.capitalize()} '{plugin_id}' published successfully",
        data={"plugin_id": plugin_id, "status": RegistrationStatus.PUBLISHED.value}
    )


def unpublish_plugin(plugin_type: PluginType, plugin_id: str) -> PluginOperationResult:
    """
    Unpublish a plugin (change status from Pub to OK).
    
    Args:
        plugin_type: "node" or "workflow"
        plugin_id: Plugin identifier
        
    Returns:
        PluginOperationResult
    """
    from .sqlalchemy.enums import RegistrationStatus
    from ..extensions import db
    
    repo = _get_repository(plugin_type)
    
    # Get plugin from DB
    plugin = repo.get_by_id(plugin_id)
    if not plugin:
        return PluginOperationResult(
            success=False,
            message=f"{plugin_type.capitalize()} '{plugin_id}' not found in database"
        )
    
    # Check current status
    if plugin.registration_status != RegistrationStatus.PUBLISHED.value:
        return PluginOperationResult(
            success=False,
            message=f"{plugin_type.capitalize()} '{plugin_id}' is not published (status: {plugin.registration_status})"
        )
    
    # Update status
    try:
        plugin.registration_status = RegistrationStatus.OK.value
        plugin.updated_at = datetime.utcnow()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to unpublish {plugin_type}: {e}")
        return PluginOperationResult(
            success=False,
            message=f"Database error: {str(e)}"
        )
    
    return PluginOperationResult(
        success=True,
        message=f"{plugin_type.capitalize()} '{plugin_id}' unpublished successfully",
        data={"plugin_id": plugin_id, "status": RegistrationStatus.OK.value}
    )


# =============================================================================
# Update Plugin
# =============================================================================

def update_plugin(
    plugin_type: PluginType,
    plugin_id: str,
    fields: Dict[str, Any]
) -> PluginOperationResult:
    """
    Update plugin fields in database.
    
    Allowed fields: name, class_name, module_path, updated_by
    
    If class_name or module_path are changed, status is set to Error
    and the user should run 'reload' to re-register.
    
    Args:
        plugin_type: "node" or "workflow"
        plugin_id: Plugin identifier
        fields: Dictionary of fields to update
        
    Returns:
        PluginOperationResult
    """
    from .sqlalchemy.enums import RegistrationStatus
    from ..extensions import db
    
    repo = _get_repository(plugin_type)
    registry = _get_registry()
    
    # Get plugin from DB
    plugin = repo.get_by_id(plugin_id)
    if not plugin:
        return PluginOperationResult(
            success=False,
            message=f"{plugin_type.capitalize()} '{plugin_id}' not found in database"
        )
    
    # Allowed fields
    allowed_fields = {"name", "class_name", "module_path", "updated_by"}
    
    # Filter to allowed fields only
    update_fields = {k: v for k, v in fields.items() if k in allowed_fields}
    
    if not update_fields:
        return PluginOperationResult(
            success=False,
            message=f"No valid fields to update. Allowed: {', '.join(allowed_fields)}"
        )
    
    # Check if critical fields are being changed (requires re-registration)
    critical_fields_changed = "class_name" in update_fields or "module_path" in update_fields
    needs_reload = False
    
    if critical_fields_changed:
        # Check if values actually changed
        if "class_name" in update_fields and update_fields["class_name"] != plugin.class_name:
            needs_reload = True
        if "module_path" in update_fields and update_fields["module_path"] != plugin.module_path:
            needs_reload = True
    
    # Update fields
    try:
        for key, value in update_fields.items():
            setattr(plugin, key, value)
        plugin.updated_at = datetime.utcnow()
        
        # If critical fields changed, set status to Error and remove from registry
        if needs_reload:
            plugin.registration_status = RegistrationStatus.ERROR.value
            # Remove stale entry from registry
            if plugin_type == "node":
                registry.unregister_node(plugin_id)
            else:
                registry.unregister_workflow(plugin_id)
        
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to update {plugin_type}: {e}")
        return PluginOperationResult(
            success=False,
            message=f"Database error: {str(e)}"
        )
    
    # Build response message
    if needs_reload:
        message = f"{plugin_type.capitalize()} '{plugin_id}' updated. Status set to 'Error'. Use 'reload {plugin_type} {plugin_id}' to re-register."
    else:
        message = f"{plugin_type.capitalize()} '{plugin_id}' updated successfully"
    
    return PluginOperationResult(
        success=True,
        message=message,
        data={
            "plugin_id": plugin_id,
            "updated_fields": list(update_fields.keys()),
            "needs_reload": needs_reload,
            "status": plugin.registration_status
        }
    )


# =============================================================================
# Get Plugin Info
# =============================================================================

def get_plugin_info(plugin_type: PluginType, plugin_id: str) -> PluginOperationResult:
    """
    Get detailed information about a plugin.
    
    Returns DB record, file existence, registry status.
    
    Args:
        plugin_type: "node" or "workflow"
        plugin_id: Plugin identifier
        
    Returns:
        PluginOperationResult with plugin info in data
    """
    repo = _get_repository(plugin_type)
    registry = _get_registry()
    
    # Get plugin from DB
    plugin = repo.get_by_id(plugin_id)
    
    # Check if in registry
    if plugin_type == "node":
        in_registry = registry.get_node(plugin_id) is not None
    else:
        in_registry = registry.get_workflow(plugin_id) is not None
    
    # Build info
    info = {
        "plugin_id": plugin_id,
        "plugin_type": plugin_type,
        "in_database": plugin is not None,
        "in_registry": in_registry,
    }
    
    if plugin:
        # Add DB info
        info["db_record"] = plugin.to_dict()
        
        # Check file existence
        file_path = _resolve_file_path(plugin_type, plugin.module_path)
        info["file_path"] = file_path
        info["file_exists"] = file_path and os.path.exists(file_path)
    else:
        # Plugin not in DB - cannot determine file path without module_path
        info["file_path"] = None
        info["file_exists"] = False
        info["note"] = "Plugin not registered in DB. Use 'reg' to register."
    
    return PluginOperationResult(
        success=True,
        message=f"Info for {plugin_type} '{plugin_id}'",
        data=info
    )


# =============================================================================
# Reload Plugin
# =============================================================================

def reload_plugin(plugin_type: PluginType, plugin_id: str) -> PluginOperationResult:
    """
    Reload a plugin (unregister from registry and re-register).
    
    Useful after modifying plugin code.
    
    Args:
        plugin_type: "node" or "workflow"
        plugin_id: Plugin identifier
        
    Returns:
        PluginOperationResult
    """
    from nos.core.engine.plugin_loader import try_register_node, try_register_workflow
    from .sqlalchemy.enums import RegistrationStatus
    from ..extensions import db
    
    repo = _get_repository(plugin_type)
    registry = _get_registry()
    
    # Get plugin from DB
    plugin = repo.get_by_id(plugin_id)
    if not plugin:
        return PluginOperationResult(
            success=False,
            message=f"{plugin_type.capitalize()} '{plugin_id}' not found in database. Use 'reg' to register first."
        )
    
    # Unregister from registry
    if plugin_type == "node":
        registry.unregister_node(plugin_id)
    else:
        registry.unregister_workflow(plugin_id)
    
    # Re-register
    try:
        if plugin_type == "node":
            ok, error = try_register_node(plugin.module_path, plugin.class_name, plugin_id)
        else:
            ok, error = try_register_workflow(plugin.module_path, plugin.class_name, plugin_id)
        
        # Update DB status
        new_status = RegistrationStatus.OK.value if ok else RegistrationStatus.ERROR.value
        plugin.registration_status = new_status
        plugin.registration_date = datetime.utcnow()
        plugin.updated_at = datetime.utcnow()
        db.session.commit()
        
        if ok:
            return PluginOperationResult(
                success=True,
                message=f"{plugin_type.capitalize()} '{plugin_id}' reloaded successfully",
                data={"plugin_id": plugin_id, "status": new_status}
            )
        else:
            return PluginOperationResult(
                success=False,
                message=f"Reload failed: {error}",
                data={"plugin_id": plugin_id, "status": new_status, "error": error}
            )
    except Exception as e:
        db.session.rollback()
        logger.error(f"Failed to reload {plugin_type}: {e}")
        return PluginOperationResult(
            success=False,
            message=f"Reload error: {str(e)}"
        )


# =============================================================================
# Delete Plugin File
# =============================================================================

def delete_plugin_file(plugin_type: PluginType, plugin_id: str) -> PluginOperationResult:
    """
    Delete plugin file from file system.
    
    WARNING: This is destructive! Also unregisters and removes DB record.
    
    Args:
        plugin_type: "node" or "workflow"
        plugin_id: Plugin identifier
        
    Returns:
        PluginOperationResult
    """
    from .sqlalchemy.enums import RegistrationStatus
    from ..extensions import db
    
    repo = _get_repository(plugin_type)
    registry = _get_registry()
    
    # Get plugin from DB (optional)
    plugin = repo.get_by_id(plugin_id)
    
    # Plugin must be in DB to know file path
    if not plugin:
        return PluginOperationResult(
            success=False,
            message=f"{plugin_type.capitalize()} '{plugin_id}' not found in database. Register it first with 'reg'."
        )
    
    # Check if published - cannot delete published plugins
    if plugin.registration_status == RegistrationStatus.PUBLISHED.value:
        return PluginOperationResult(
            success=False,
            message=f"Cannot delete published {plugin_type}. Use 'unpub' first."
        )
    
    # Determine file path from DB record
    file_path = _resolve_file_path(plugin_type, plugin.module_path)
    
    if not file_path:
        return PluginOperationResult(
            success=False,
            message=f"Could not resolve file path for {plugin_type} '{plugin_id}'"
        )
    
    if not os.path.exists(file_path):
        return PluginOperationResult(
            success=False,
            message=f"File not found: {file_path}"
        )
    
    # Unregister from registry
    if plugin_type == "node":
        registry.unregister_node(plugin_id)
    else:
        registry.unregister_workflow(plugin_id)
    
    # Delete from DB if exists
    if plugin:
        try:
            db.session.delete(plugin)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Failed to delete {plugin_type} from DB: {e}")
    
    # Delete file
    try:
        os.remove(file_path)
    except OSError as e:
        logger.error(f"Failed to delete file: {e}")
        return PluginOperationResult(
            success=False,
            message=f"Failed to delete file: {str(e)}"
        )
    
    return PluginOperationResult(
        success=True,
        message=f"{plugin_type.capitalize()} '{plugin_id}' deleted (file + DB record)",
        data={"plugin_id": plugin_id, "file_path": file_path}
    )


# =============================================================================
# Rename Plugin
# =============================================================================

def rename_plugin(
    plugin_type: PluginType,
    old_id: str,
    new_id: str
) -> PluginOperationResult:
    """
    Rename a plugin (rename file and update DB record).
    
    Args:
        plugin_type: "node" or "workflow"
        old_id: Current plugin identifier
        new_id: New plugin identifier
        
    Returns:
        PluginOperationResult
    """
    from .sqlalchemy.enums import RegistrationStatus
    from ..extensions import db
    from .plugin_code_service import resolve_node_path, resolve_workflow_path
    
    repo = _get_repository(plugin_type)
    registry = _get_registry()
    
    # Get plugin from DB
    plugin = repo.get_by_id(old_id)
    if not plugin:
        return PluginOperationResult(
            success=False,
            message=f"{plugin_type.capitalize()} '{old_id}' not found in database"
        )
    
    # Check if published
    if plugin.registration_status == RegistrationStatus.PUBLISHED.value:
        return PluginOperationResult(
            success=False,
            message=f"Cannot rename published {plugin_type}. Use 'unpub' first."
        )
    
    # Check if new_id already exists
    if repo.get_by_id(new_id):
        return PluginOperationResult(
            success=False,
            message=f"{plugin_type.capitalize()} '{new_id}' already exists"
        )
    
    # Get old file path
    old_file_path = _resolve_file_path(plugin_type, plugin.module_path)
    if not old_file_path or not os.path.exists(old_file_path):
        return PluginOperationResult(
            success=False,
            message=f"Source file not found: {old_file_path}"
        )
    
    # Calculate new module path and file path
    old_parts = plugin.module_path.rsplit(".", 1)
    new_module_path = f"{old_parts[0]}.{new_id}" if len(old_parts) > 1 else new_id
    new_file_path = _resolve_file_path(plugin_type, new_module_path)
    
    if not new_file_path:
        return PluginOperationResult(
            success=False,
            message=f"Could not resolve new file path for '{new_id}'"
        )
    
    # Rename file
    try:
        os.rename(old_file_path, new_file_path)
    except OSError as e:
        logger.error(f"Failed to rename file: {e}")
        return PluginOperationResult(
            success=False,
            message=f"Failed to rename file: {str(e)}"
        )
    
    # Unregister old from registry
    if plugin_type == "node":
        registry.unregister_node(old_id)
    else:
        registry.unregister_workflow(old_id)
    
    # Update DB: delete old, create new
    try:
        # Create new record
        id_field = f"{plugin_type}_id"
        new_plugin_data = plugin.to_dict()
        new_plugin_data[id_field] = new_id
        new_plugin_data["module_path"] = new_module_path
        new_plugin_data["registration_status"] = RegistrationStatus.ERROR.value  # Needs re-registration
        
        # Delete old record
        db.session.delete(plugin)
        db.session.flush()
        
        # Create new record
        repo.create(
            **{id_field: new_id},
            class_name=new_plugin_data["class_name"],
            module_path=new_module_path,
            name=new_plugin_data.get("name"),
            created_by=new_plugin_data.get("created_by", "console"),
            updated_by="console",
            registration_status=RegistrationStatus.ERROR.value,
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        # Try to restore file
        try:
            os.rename(new_file_path, old_file_path)
        except:
            pass
        logger.error(f"Failed to update DB: {e}")
        return PluginOperationResult(
            success=False,
            message=f"Database error: {str(e)}"
        )
    
    return PluginOperationResult(
        success=True,
        message=f"{plugin_type.capitalize()} renamed: '{old_id}' → '{new_id}'. Use 'reg' to re-register.",
        data={
            "old_id": old_id,
            "new_id": new_id,
            "old_file": old_file_path,
            "new_file": new_file_path
        }
    )


# =============================================================================
# Copy Plugin
# =============================================================================

def copy_plugin(
    plugin_type: PluginType,
    source_id: str,
    new_id: str
) -> PluginOperationResult:
    """
    Copy/duplicate a plugin (copy file and create new DB record).
    
    Args:
        plugin_type: "node" or "workflow"
        source_id: Source plugin identifier
        new_id: New plugin identifier
        
    Returns:
        PluginOperationResult
    """
    from .sqlalchemy.enums import RegistrationStatus
    from ..extensions import db
    
    repo = _get_repository(plugin_type)
    
    # Source plugin must be in DB to know file path
    source_plugin = repo.get_by_id(source_id)
    if not source_plugin:
        return PluginOperationResult(
            success=False,
            message=f"Source {plugin_type} '{source_id}' not found in database. Register it first with 'reg'."
        )
    
    # Check if new_id already exists
    if repo.get_by_id(new_id):
        return PluginOperationResult(
            success=False,
            message=f"{plugin_type.capitalize()} '{new_id}' already exists in database"
        )
    
    # Determine source file path from DB record
    source_file_path = _resolve_file_path(plugin_type, source_plugin.module_path)
    source_module_path = source_plugin.module_path
    
    if not source_file_path or not os.path.exists(source_file_path):
        return PluginOperationResult(
            success=False,
            message=f"Source file not found: {source_file_path}"
        )
    
    # Calculate new module path and file path
    old_parts = source_module_path.rsplit(".", 1)
    new_module_path = f"{old_parts[0]}.{new_id}" if len(old_parts) > 1 else new_id
    new_file_path = _resolve_file_path(plugin_type, new_module_path)
    
    if not new_file_path:
        return PluginOperationResult(
            success=False,
            message=f"Could not resolve new file path for '{new_id}'"
        )
    
    if os.path.exists(new_file_path):
        return PluginOperationResult(
            success=False,
            message=f"Target file already exists: {new_file_path}"
        )
    
    # Copy file
    try:
        shutil.copy2(source_file_path, new_file_path)
    except OSError as e:
        logger.error(f"Failed to copy file: {e}")
        return PluginOperationResult(
            success=False,
            message=f"Failed to copy file: {str(e)}"
        )
    
    # Generate class name from new_id
    new_class_name = "".join(word.capitalize() for word in new_id.split("_"))
    if plugin_type == "node" and not new_class_name.endswith("Node"):
        new_class_name += "Node"
    elif plugin_type == "workflow" and not new_class_name.endswith("Workflow"):
        new_class_name += "Workflow"
    
    return PluginOperationResult(
        success=True,
        message=f"{plugin_type.capitalize()} copied: '{source_id}' → '{new_id}'. Edit the file and use 'reg' to register.",
        data={
            "source_id": source_id,
            "new_id": new_id,
            "source_file": source_file_path,
            "new_file": new_file_path,
            "new_module_path": new_module_path,
            "suggested_class_name": new_class_name
        }
    )
