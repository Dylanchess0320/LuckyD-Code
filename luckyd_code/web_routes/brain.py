"""Knowledge graph / brain routes."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/api/brain")
async def brain_status(request: Request):
    from ..brain import KnowledgeGraph, Retriever, VectorIndexer
    brain = KnowledgeGraph()
    brain.load()

    rag_available = False
    try:
        idx = VectorIndexer()
        rag_available = idx.load()
    except Exception:
        pass

    if not brain.nodes and not rag_available:
        return {"status": "empty", "message": "Knowledge graph is empty. Use /api/brain/rebuild to index your codebase."}

    result = {
        "symbols": brain.stats.get("node_count", 0),
        "relations": brain.stats.get("edge_count", 0),
        "files_parsed": brain.stats.get("files_parsed", 0),
    }
    if brain.stats.get("last_built"):
        import time
        result["last_built"] = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(brain.stats["last_built"]))

    if rag_available:
        try:
            r = Retriever()
            info = r.stats()
            vec = info.get("vector", {})
            result["rag_chunks"] = vec.get("chunks", 0)
            result["rag_files"] = vec.get("files", 0)
        except Exception:
            pass

    return result


@router.post("/api/brain/rebuild")
async def brain_rebuild(request: Request):
    from ..brain import rebuild_project
    import os
    result = rebuild_project(os.getcwd())

    state = request.app.state.web_state
    if state.knowledge_graph:
        state.knowledge_graph.load()

    return {
        "status": "ok",
        "chunks": result.get("chunks", 0),
        "files": result.get("files", 0),
        "symbols": result.get("node_count", 0),
        "files_parsed": result.get("files_parsed", 0),
    }


@router.get("/api/brain/search")
async def brain_search(request: Request, q: str = "", max_results: int = 5):
    if not q:
        return {"results": []}
    try:
        from ..brain import Retriever
        r = Retriever()
        results = r.search(q, k=max_results)
        formatted = []
        for res in results:
            formatted.append({
                "content": res.get("content", "")[:500],
                "file": res.get("file", ""),
                "score": res.get("score", 0),
            })
        return {"results": formatted}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/brain/stats")
async def brain_stats(request: Request):
    try:
        from ..brain import Retriever
        r = Retriever()
        info = r.stats()
        return info
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/brain/dependents")
async def brain_dependents(request: Request, symbol: str = ""):
    """Find all nodes that depend on a symbol in the knowledge graph."""
    if not symbol:
        return JSONResponse({"error": "symbol parameter required"}, status_code=400)
    try:
        from ..brain import KnowledgeGraph
        kg = KnowledgeGraph()
        kg.load()
        deps = kg.find_dependents(symbol)
        return {"symbol": symbol, "dependents": deps, "count": len(deps)}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
