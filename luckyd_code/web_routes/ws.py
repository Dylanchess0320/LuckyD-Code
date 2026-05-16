"""WebSocket chat handler with tool execution, model fallback, and streaming."""

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..api import _repair_json
from ..log import get_logger

logger = get_logger()
router = APIRouter()

MAX_MESSAGE_LENGTH = 10000
MAX_TOOL_LOOPS = 100


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):  # pragma: no cover
    await ws.accept()
    from ..api import stream_chat

    state = ws.app.state.web_state
    config = state.config
    context = state.context
    registry = state.registry
    mcp = state.mcp
    memory_module = state.memory_module

    try:
        while True:
            data = await asyncio.wait_for(ws.receive_text(), timeout=300.0)
            msg = json.loads(data)
            msg_type = msg.get("type", "message")

            if msg_type == "message":
                user_text = msg.get("content", "").strip()
                if not user_text:
                    continue

                if len(user_text) > MAX_MESSAGE_LENGTH:
                    await ws.send_json({
                        "type": "error",
                        "content": f"Message too long (max {MAX_MESSAGE_LENGTH} characters)",
                    })
                    continue

                context.add_user_message(user_text)

                text_buffer = ""
                pending_tool_calls = None
                tool_loop_count = 0
                tool_call_count = 0
                active_model = config.model
                current_tier = 2

                from .. import settings as cfg
                web_settings = cfg.load_settings()
                auto_route = web_settings.get("auto_route", True)
                from ..router import resolve_initial_route, escalate_tier
                routing = resolve_initial_route(
                    user_text, 0, config.provider, config.model, auto_route,
                )
                if routing.tier_changed:
                    active_model = routing.model
                    await ws.send_json({
                        "type": "text",
                        "content": f"[Routing: {routing.tier_description} → {active_model}]\n\n",
                    })

                all_tools = registry.list_tools()
                all_tools.extend(mcp.get_all_tools())

                while tool_loop_count < MAX_TOOL_LOOPS:
                    messages = context.get_messages()
                    text_buffer = ""
                    pending_tool_calls = None
                    tool_reasoning = ""

                    if auto_route:
                        escalation = escalate_tier(
                            user_text, tool_call_count, config.provider,
                            config.model, active_model, current_tier, auto_route,
                        )
                        if escalation.tier_changed:
                            active_model = escalation.model
                            current_tier = escalation.tier
                            await ws.send_json({
                                "type": "text",
                                "content": f"[Escalating: {escalation.tier_description} → {active_model}]\n\n",
                            })

                    for event_type, evt_data in stream_chat(
                        messages=messages,
                        tools=all_tools,
                        model=active_model,
                        api_key=config.api_key,
                        base_url=config.base_url,
                        max_tokens=config.max_tokens,
                        temperature=config.temperature,
                    ):
                        if event_type == "text":
                            text_buffer += evt_data
                            await ws.send_json({
                                "type": "text",
                                "content": evt_data,
                            })
                        elif event_type == "tool_calls":
                            pending_tool_calls, tool_reasoning = evt_data
                        elif event_type == "model_not_found":
                            await ws.send_json({
                                "type": "error",
                                "content": f"Model not found: {evt_data[:300]}",
                            })
                            break
                        elif event_type == "error":
                            await ws.send_json({
                                "type": "error",
                                "content": f"API error: {evt_data[:500]}",
                            })
                            break
                        elif event_type == "done":
                            content, reasoning = evt_data
                            if reasoning:
                                context.add_assistant_message(content=content or text_buffer, reasoning_content=reasoning)
                            elif content or text_buffer:
                                context.add_assistant_message(content=content or text_buffer)
                            text_buffer = ""

                    if pending_tool_calls:
                        context.add_assistant_message(
                            text_buffer or None,
                            tool_calls=pending_tool_calls,
                            reasoning_content=tool_reasoning or None,
                        )

                        for tc in pending_tool_calls:
                            name = tc["function"]["name"]
                            raw_args = tc["function"]["arguments"]
                            try:
                                args = json.loads(_repair_json(raw_args)) if raw_args else {}
                            except json.JSONDecodeError:
                                await ws.send_json({
                                    "type": "tool",
                                    "name": name,
                                    "content": f"Invalid JSON arguments: {raw_args[:200]}",
                                })
                                context.add_tool_result(
                                    tool_call_id=tc["id"], tool_name=name,
                                    result=f"Error: invalid JSON in tool arguments: {raw_args[:200]}",
                                )
                                continue

                            await ws.send_json({
                                "type": "tool",
                                "name": name,
                                "content": f"Running {name}...",
                            })

                            try:
                                if name.startswith("mcp_"):
                                    result = mcp.execute(name, args)
                                else:
                                    result = registry.execute(name, args)
                            except Exception as e:
                                result = f"Error executing {name}: {e}"

                            result_preview = result[:300].replace("\n", " ")
                            if len(result) > 300:
                                result_preview += "..."

                            await ws.send_json({
                                "type": "tool_result",
                                "name": name,
                                "content": result_preview,
                            })

                            context.add_tool_result(
                                tool_call_id=tc["id"],
                                tool_name=name,
                                result=result,
                            )
                            tool_call_count += 1

                        tool_loop_count += 1
                        continue

                    if text_buffer:
                        context.add_assistant_message(content=text_buffer)
                    await ws.send_json({"type": "done"})
                    break

                if tool_loop_count >= MAX_TOOL_LOOPS:
                    await ws.send_json({
                        "type": "error",
                        "content": "Max tool loop iterations reached",
                    })

            elif msg_type == "clear":
                context.reset()
                md = memory_module.load_claude_md()
                session_memories = state.web_memory_mgr.get_all_memories_formatted()
                if md and session_memories:
                    merged = md + "\n\n" + session_memories
                elif session_memories:
                    merged = session_memories
                else:
                    merged = md or ""
                if merged:
                    context.messages.insert(1, {
                        "role": "user",
                        "content": f"<claude-md>{merged}</claude-md>",
                    })
                await ws.send_json({"type": "cleared"})

    except asyncio.TimeoutError:
        try:
            await ws.send_json({"type": "error", "content": "Request timed out (300s)"})
        except Exception:
            logger.warning("WebSocket send_json (timeout) failed", exc_info=True)
        try:
            await ws.close(code=1001)
        except Exception:
            logger.warning("WebSocket close failed", exc_info=True)
    except WebSocketDisconnect:
        pass
    except json.JSONDecodeError:
        try:
            await ws.send_json({"type": "error", "content": "Invalid JSON"})
        except Exception:
            logger.warning("WebSocket send_json (invalid JSON) failed", exc_info=True)
    except Exception as e:
        logger.warning(f"WebSocket error: {e}")
        try:
            await ws.send_json({"type": "error", "content": f"Server error: {str(e)[:200]}"})
        except Exception:
            logger.warning("WebSocket send_json (error notification) failed", exc_info=True)
