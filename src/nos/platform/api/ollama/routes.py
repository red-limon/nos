"""
Ollama API routes.

Provides REST endpoints for interacting with the Ollama LLM server.
Uses the centralized OllamaService for all operations.

Endpoints:
- GET /api/ollama/ping       Check server availability
- GET /api/ollama/models     List available models
- GET /api/ollama/models/<name>  Get model details
- POST /api/ollama/chat      Send chat message (non-streaming)
- POST /api/ollama/generate  Generate completion (non-streaming)
"""

import logging
from flask import jsonify, request

from ..routes import api_bp
from ...services.ai.ollama_service import ollama

logger = logging.getLogger(__name__)


@api_bp.get("/ollama/ping")
@api_bp.get("/ollama/ping/")
def ollama_ping():
    """
    Check if Ollama server is available.
    
    Returns:
        {
            "success": true,
            "status": "online" | "offline",
            "base_url": "http://localhost:11434",
            "default_model": "llama3.2"
        }
    """
    try:
        is_available = ollama.is_available()
        
        return jsonify({
            "success": True,
            "status": "online" if is_available else "offline",
            "base_url": ollama.base_url,
            "default_model": ollama.default_model
        })
        
    except Exception as e:
        logger.error(f"Ollama ping error: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "status": "error",
            "error": str(e),
            "base_url": ollama.base_url
        }), 500


@api_bp.get("/ollama/models")
@api_bp.get("/ollama/models/")
def ollama_list_models():
    """
    List all models available on the Ollama server.
    
    Returns:
        {
            "success": true,
            "models": [
                {
                    "name": "llama3:8b",
                    "size": 4661224428,
                    "size_formatted": "4.3 GB",
                    "digest": "abc123...",
                    "modified_at": "2024-01-15T..."
                }
            ],
            "count": 5,
            "server": "http://localhost:11434"
        }
    """
    try:
        models = ollama.list_models()
        
        models_data = []
        for m in models:
            size_gb = m.size / (1024 ** 3)
            if size_gb >= 1:
                size_str = f"{size_gb:.1f} GB"
            else:
                size_mb = m.size / (1024 ** 2)
                size_str = f"{size_mb:.0f} MB"
            
            models_data.append({
                "name": m.name,
                "size": m.size,
                "size_formatted": size_str,
                "digest": m.digest,
                "modified_at": m.modified_at,
                "details": m.details
            })
        
        return jsonify({
            "success": True,
            "models": models_data,
            "count": len(models_data),
            "server": ollama.base_url
        })
        
    except Exception as e:
        logger.error(f"Ollama list models error: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "models": [],
            "error": str(e),
            "server": ollama.base_url
        }), 500


@api_bp.get("/ollama/models/<model_name>")
@api_bp.get("/ollama/models/<model_name>/")
def ollama_get_model(model_name: str):
    """
    Get detailed information about a specific model.
    
    Args:
        model_name: Name of the model (e.g., "llama3:8b")
    
    Returns:
        Model details from Ollama server
    """
    try:
        model_info = ollama.get_model_info(model_name)
        
        if model_info:
            return jsonify({
                "success": True,
                "model": model_name,
                "info": model_info
            })
        else:
            return jsonify({
                "success": False,
                "model": model_name,
                "error": f"Model '{model_name}' not found"
            }), 404
            
    except Exception as e:
        logger.error(f"Ollama get model error: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "model": model_name,
            "error": str(e)
        }), 500


@api_bp.post("/ollama/chat")
@api_bp.post("/ollama/chat/")
def ollama_chat():
    """
    Send a chat message to Ollama (non-streaming).
    
    Request body:
        {
            "prompt": "Hello, how are you?",
            "model": "llama3:8b",        // optional, uses default
            "system": "You are helpful",  // optional
            "temperature": 0.7,           // optional
            "history": [                  // optional
                {"role": "user", "content": "..."},
                {"role": "assistant", "content": "..."}
            ]
        }
    
    Returns:
        {
            "success": true,
            "content": "I'm doing well, thank you!",
            "model": "llama3:8b",
            "eval_count": 25,
            "total_duration_ms": 1234
        }
    """
    data = request.get_json()
    
    if not data:
        return jsonify({"success": False, "error": "Request body must be JSON"}), 400
    
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"success": False, "error": "Missing required field: prompt"}), 400
    
    model = data.get("model")
    system = data.get("system")
    temperature = data.get("temperature", 0.7)
    history = data.get("history")
    
    try:
        response = ollama.chat(
            prompt=prompt,
            model=model,
            system=system,
            history=history,
            temperature=temperature
        )
        
        if response.success:
            result = {
                "success": True,
                "content": response.content,
                "model": response.model
            }
            if response.eval_count:
                result["eval_count"] = response.eval_count
            if response.total_duration:
                result["total_duration_ms"] = response.total_duration / 1_000_000
            return jsonify(result)
        else:
            return jsonify({
                "success": False,
                "error": response.error,
                "model": response.model
            }), 500
            
    except Exception as e:
        logger.error(f"Ollama chat error: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@api_bp.post("/ollama/generate")
@api_bp.post("/ollama/generate/")
def ollama_generate():
    """
    Generate a completion (non-chat mode).
    
    Request body:
        {
            "prompt": "Complete this: def hello():",
            "model": "codellama",        // optional
            "system": "You are expert",   // optional
            "temperature": 0.7            // optional
        }
    
    Returns:
        {
            "success": true,
            "content": "    return 'Hello, World!'",
            "model": "codellama"
        }
    """
    data = request.get_json()
    
    if not data:
        return jsonify({"success": False, "error": "Request body must be JSON"}), 400
    
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return jsonify({"success": False, "error": "Missing required field: prompt"}), 400
    
    model = data.get("model")
    system = data.get("system")
    temperature = data.get("temperature", 0.7)
    
    try:
        response = ollama.generate(
            prompt=prompt,
            model=model,
            system=system,
            temperature=temperature
        )
        
        if response.success:
            result = {
                "success": True,
                "content": response.content,
                "model": response.model
            }
            if response.eval_count:
                result["eval_count"] = response.eval_count
            if response.total_duration:
                result["total_duration_ms"] = response.total_duration / 1_000_000
            return jsonify(result)
        else:
            return jsonify({
                "success": False,
                "error": response.error,
                "model": response.model
            }), 500
            
    except Exception as e:
        logger.error(f"Ollama generate error: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@api_bp.post("/ollama/embeddings")
@api_bp.post("/ollama/embeddings/")
def ollama_embeddings():
    """
    Generate embeddings for text.
    
    Request body:
        {
            "text": "Hello world",     // string or array of strings
            "model": "nomic-embed-text" // optional
        }
    
    Returns:
        {
            "success": true,
            "embedding": [0.1, 0.2, ...],  // or "embeddings" for batch
            "model": "nomic-embed-text"
        }
    """
    data = request.get_json()
    
    if not data:
        return jsonify({"success": False, "error": "Request body must be JSON"}), 400
    
    text = data.get("text")
    if not text:
        return jsonify({"success": False, "error": "Missing required field: text"}), 400
    
    model = data.get("model")
    
    try:
        result = ollama.embeddings(text=text, model=model)
        
        if "error" in result:
            return jsonify({
                "success": False,
                "error": result["error"],
                "model": result.get("model")
            }), 500
        
        return jsonify({
            "success": True,
            **result
        })
        
    except Exception as e:
        logger.error(f"Ollama embeddings error: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
