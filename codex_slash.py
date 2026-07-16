# -*- coding: utf-8 -*-
"""Codex slash command, lifecycle, goal, and manual MCP helpers."""
import json
import shlex
import time

import codex_account
import codex_command_exec
import codex_config
import codex_inventory
import codex_mcp_status
import codex_text
import common


class CodexSlashAdapter:
    def __init__(self, session):
        object.__setattr__(self, "session", session)

    def __getattr__(self, name):
        return getattr(self.session, name)

    def __setattr__(self, name, value):
        if name == "session":
            object.__setattr__(self, name, value)
            return
        setattr(self.session, name, value)

    def handle_slash_command(self, command):
        text = (command or "").strip()
        if not text.startswith("/"):
            return {"ok": False, "error": "not a slash command"}
        name, _, rest = text.partition(" ")
        name = name.lower()
        arg = rest.strip()
        if name == "/model":
            return self.set_model(arg)
        if name == "/compact":
            return self.start_compaction()
        if name == "/approval":
            return self.set_approval_policy(arg)
        if name == "/sandbox":
            return self.set_sandbox_mode(arg)
        if name == "/search":
            return self.set_web_search(arg)
        if name == "/reasoning":
            return self.set_reasoning_effort(arg)
        if name == "/summary":
            return self.set_reasoning_summary(arg)
        if name == "/service-tier":
            return self.set_service_tier(arg)
        if name in ("/writable-roots", "/add-dir"):
            return self.set_writable_roots(arg)
        if name == "/rename":
            return self.rename_thread(arg)
        if name == "/archive":
            return self.archive_thread()
        if name == "/unarchive":
            return self.unarchive_thread()
        if name == "/fork":
            return self.fork_thread()
        if name == "/rollback":
            return self.rollback_thread(arg)
        if name == "/steer":
            return self.steer_turn(arg)
        if name == "/goal":
            return self.goal_command(arg)
        if name == "/mcp-resource":
            return self.read_mcp_resource(arg)
        if name == "/mcp-status":
            return self.list_mcp_status(arg)
        if name == "/mcp-resources":
            return self.list_mcp_resources(arg)
        if name == "/mcp-tool":
            return self.call_mcp_tool(arg)
        if name == "/skills":
            return self.list_skills(arg)
        if name == "/plugins":
            return self.list_plugins(arg)
        if name in ("/account-status", "/account"):
            return self.account_status(arg)
        if name == "/exec":
            return self.command_exec(arg)
        return {"ok": False, "error": "unsupported Codex slash command: %s" % name}

    def set_model(self, model):
        model = (model or "").strip()
        if not model:
            current = self.cfg.get("model") or self.model or "default"
            return {"ok": False, "error": "usage: /model <model-id> (current: %s)" % current}
        self.cfg["model"] = model
        self.model = model
        self._sync_collaboration_mode()
        self._record_and_broadcast({"type": "system", "model": model})
        self._codex_notice("Model set for subsequent Codex turns: %s" % model, "slash/model")
        self._persist()
        return {"ok": True, "command": "model", "model": model}

    def set_approval_policy(self, policy):
        policy = (policy or "").strip()
        if policy not in codex_config.APPROVAL_POLICIES:
            return {
                "ok": False,
                "error": "usage: /approval %s" % "|".join(codex_config.APPROVAL_POLICIES),
            }
        if self.yolo:
            return {"ok": False, "error": "auto approve is enabled for this session; restart with auto approve off first"}
        self.cfg["approval_policy"] = policy
        self._codex_notice("Approval policy set for subsequent Codex turns: %s" % policy, "slash/approval")
        self._persist()
        return {"ok": True, "command": "approval", "approval_policy": policy}

    def set_sandbox_mode(self, mode):
        mode = (mode or "").strip()
        if mode not in codex_config.SANDBOX_MODES:
            return {
                "ok": False,
                "error": "usage: /sandbox %s" % "|".join(codex_config.SANDBOX_MODES),
            }
        if self.yolo:
            return {"ok": False, "error": "auto approve is enabled for this session; restart with auto approve off first"}
        self.cfg["sandbox"] = mode
        self._codex_notice("Sandbox set for subsequent Codex turns: %s" % mode, "slash/sandbox")
        self._persist()
        return {"ok": True, "command": "sandbox", "sandbox": mode}

    def set_web_search(self, mode):
        mode = (mode or "").strip().lower()
        aliases = {"on": "live", "off": "disabled", "true": "live", "false": "disabled"}
        mode = aliases.get(mode, mode)
        if mode not in codex_config.WEB_SEARCH_MODES:
            return {
                "ok": False,
                "error": "usage: /search %s" % "|".join(codex_config.WEB_SEARCH_MODES),
            }
        if self.thread_id:
            return {
                "ok": False,
                "error": "web search is only configurable before the Codex thread starts; use the launch modal for existing threads",
            }
        self.cfg["web_search"] = mode
        self._codex_notice("Web search will be %s when this Codex thread starts" % mode, "slash/search")
        self._persist()
        return {"ok": True, "command": "search", "web_search": mode}

    def set_reasoning_effort(self, effort):
        effort = (effort or "").strip()
        if not effort:
            return {"ok": False, "error": "usage: /reasoning <effort> (for example low|medium|high)"}
        self.cfg["reasoning_effort"] = effort
        self._sync_collaboration_mode()
        self._codex_notice("Reasoning effort set for subsequent Codex turns: %s" % effort, "slash/reasoning")
        self._persist()
        return {"ok": True, "command": "reasoning", "reasoning_effort": effort}

    def set_reasoning_summary(self, summary):
        summary = (summary or "").strip().lower()
        if summary not in codex_config.REASONING_SUMMARIES:
            return {
                "ok": False,
                "error": "usage: /summary %s" % "|".join(codex_config.REASONING_SUMMARIES),
            }
        self.cfg["reasoning_summary"] = summary
        self._codex_notice("Reasoning summary set for subsequent Codex turns: %s" % summary, "slash/summary")
        self._persist()
        return {"ok": True, "command": "summary", "reasoning_summary": summary}

    def set_service_tier(self, tier):
        tier = (tier or "").strip()
        if not tier:
            self.cfg.pop("service_tier", None)
            self._codex_notice("Service tier override cleared for subsequent Codex turns", "slash/service-tier")
            self._persist()
            return {"ok": True, "command": "service-tier", "service_tier": ""}
        self.cfg["service_tier"] = tier
        self._codex_notice("Service tier set for subsequent Codex turns: %s" % tier, "slash/service-tier")
        self._persist()
        return {"ok": True, "command": "service-tier", "service_tier": tier}

    def set_writable_roots(self, roots_text):
        roots = codex_config.normalize_writable_roots(roots_text, cwd=self.cwd)
        denied = [root for root in roots if not common.path_allowed_for_user(self.user, root)]
        if denied:
            return {"ok": False, "error": "writable root is outside this user's workspaces: %s" % denied[0]}
        if not roots:
            self.cfg.pop("writable_roots", None)
            self._codex_notice("Additional writable roots cleared for subsequent Codex turns", "slash/writable-roots")
            self._persist()
            return {"ok": True, "command": "writable-roots", "writable_roots": []}
        self.cfg["writable_roots"] = roots
        self._codex_notice(
            "Additional writable roots set for subsequent Codex turns: %s" % ", ".join(roots),
            "slash/writable-roots",
        )
        self._persist()
        return {"ok": True, "command": "writable-roots", "writable_roots": roots}

    def start_compaction(self):
        self._ensure_thread()
        if not self.thread_id:
            return {"ok": False, "error": "Codex thread is not ready"}
        self._busy = True
        self._compact_in_progress = True
        self.current_turn_started_at = time.time()
        try:
            self._client().request("thread/compact/start", {"threadId": self.thread_id}, timeout=30)
        except Exception:
            self._busy = False
            self._compact_in_progress = False
            self.current_turn_started_at = None
            raise
        self._codex_notice("Started Codex context compaction", "thread/compact/start")
        self._persist()
        return {"ok": True, "command": "compact"}

    def rename_thread(self, name):
        name = (name or "").strip()
        if not name:
            return {"ok": False, "error": "usage: /rename <thread name>"}
        self._ensure_thread()
        if not self.thread_id:
            return {"ok": False, "error": "Codex thread is not ready"}
        self._client().request(
            "thread/name/set", {"threadId": self.thread_id, "name": name}, timeout=30)
        self._codex_notice("Thread renamed: %s" % name, "thread/name/set")
        self._persist()
        return {"ok": True, "command": "rename", "name": name}

    def archive_thread(self):
        self._ensure_thread()
        if not self.thread_id:
            return {"ok": False, "error": "Codex thread is not ready"}
        self._client().request("thread/archive", {"threadId": self.thread_id}, timeout=30)
        self._codex_notice("Thread archived in Codex history", "thread/archive")
        self._persist()
        return {"ok": True, "command": "archive", "thread_id": self.thread_id}

    def unarchive_thread(self):
        self._ensure_thread()
        if not self.thread_id:
            return {"ok": False, "error": "Codex thread is not ready"}
        self._client().request("thread/unarchive", {"threadId": self.thread_id}, timeout=30)
        self._codex_notice("Thread unarchived in Codex history", "thread/unarchive")
        self._persist()
        return {"ok": True, "command": "unarchive", "thread_id": self.thread_id}

    def fork_thread(self):
        self._ensure_thread()
        if not self.thread_id:
            return {"ok": False, "error": "Codex thread is not ready"}
        params = self._thread_params()
        params["threadId"] = self.thread_id
        res = self._client().request("thread/fork", params, timeout=30) or {}
        thread = res.get("thread") or {}
        fork_id = thread.get("id") or thread.get("sessionId") or ""
        if not fork_id:
            fork_id = codex_text.compact_json(thread or res)
        self._codex_notice("Thread forked: %s" % fork_id, "thread/fork")
        if thread.get("id") or thread.get("sessionId"):
            self._record_and_broadcast({
                "type": "thread_forked",
                "thread_id": fork_id,
                "cwd": self.cwd,
                "title": thread.get("title") or "Forked Codex thread",
            })
        return {"ok": True, "command": "fork", "thread_id": fork_id}

    def rollback_thread(self, count_text):
        try:
            count = int((count_text or "1").strip() or "1")
        except Exception:
            return {"ok": False, "error": "usage: /rollback [num-turns]"}
        if count < 1:
            return {"ok": False, "error": "rollback count must be >= 1"}
        self._ensure_thread()
        if not self.thread_id:
            return {"ok": False, "error": "Codex thread is not ready"}
        res = self._client().request(
            "thread/rollback",
            {"threadId": self.thread_id, "numTurns": count},
            timeout=30,
        ) or {}
        thread = res.get("thread") or {}
        self._replace_history_from_thread(thread)
        self._codex_notice("Rolled back %d Codex turn(s)" % count, "thread/rollback")
        self._persist()
        return {"ok": True, "command": "rollback", "num_turns": count}

    def steer_turn(self, prompt):
        prompt = (prompt or "").strip()
        if not prompt:
            return {"ok": False, "error": "usage: /steer <instruction for the running turn>"}
        if not self._busy or not self.thread_id or not self.last_turn_id:
            return {"ok": False, "error": "no running Codex turn to steer"}
        self._client().request(
            "turn/steer",
            {
                "threadId": self.thread_id,
                "expectedTurnId": self.last_turn_id,
                "input": self._user_input_items(prompt),
            },
            timeout=30,
        )
        self._codex_notice("Steered the running Codex turn", "turn/steer", {"prompt": prompt})
        return {"ok": True, "command": "steer"}

    def goal_command(self, arg):
        arg = (arg or "").strip()
        if not arg or arg.lower() == "get":
            return self.get_goal()
        action, _, rest = arg.partition(" ")
        action = action.strip().lower()
        rest = rest.strip()
        if action == "set":
            return self.set_goal(rest)
        if action == "clear":
            return self.clear_goal()
        if action == "status":
            return self.set_goal_status(rest)
        if action in [s.lower() for s in codex_config.GOAL_STATUSES]:
            return self.set_goal_status(action)
        return {
            "ok": False,
            "error": "usage: /goal [get|set <objective>|clear|status %s]" % "|".join(codex_config.GOAL_STATUSES),
        }

    def _ensure_goal_thread(self):
        self._ensure_thread()
        if not self.thread_id:
            return False
        return True

    def _goal_from_response(self, response):
        if isinstance(response, dict):
            goal = response.get("goal") or response.get("threadGoal")
            if isinstance(goal, dict):
                return goal
        return {}

    def _goal_summary(self, goal):
        if not isinstance(goal, dict) or not goal:
            return ""
        objective = str(goal.get("objective") or "").strip()
        status = str(goal.get("status") or "").strip()
        parts = []
        if status:
            parts.append(status)
        used = goal.get("tokensUsed")
        budget = goal.get("tokenBudget")
        if used is not None or budget is not None:
            if budget:
                parts.append("tokens %s/%s" % (used or 0, budget))
            elif used is not None:
                parts.append("tokens %s" % used)
        prefix = ("[%s] " % ", ".join(parts)) if parts else ""
        return prefix + (objective or "no objective")

    def get_goal(self):
        if not self._ensure_goal_thread():
            return {"ok": False, "error": "Codex thread is not ready"}
        res = self._client().request("thread/goal/get", {"threadId": self.thread_id}, timeout=30) or {}
        goal = self._goal_from_response(res)
        if goal:
            self._codex_notice("Goal: " + self._goal_summary(goal), "thread/goal/get", goal)
        else:
            self._codex_notice("No Codex goal is set", "thread/goal/get")
        return {"ok": True, "command": "goal", "action": "get", "goal": goal}

    def set_goal(self, objective):
        objective = (objective or "").strip()
        if not objective:
            return {"ok": False, "error": "usage: /goal set <objective>"}
        if not self._ensure_goal_thread():
            return {"ok": False, "error": "Codex thread is not ready"}
        params = {"threadId": self.thread_id, "objective": objective, "status": "active"}
        res = self._client().request("thread/goal/set", params, timeout=30) or {}
        goal = self._goal_from_response(res) or {"objective": objective, "status": "active"}
        self._codex_notice("Goal set: " + self._goal_summary(goal), "thread/goal/set", goal)
        self._persist()
        return {"ok": True, "command": "goal", "action": "set", "goal": goal}

    def set_goal_status(self, status):
        status = (status or "").strip()
        matches = {s.lower(): s for s in codex_config.GOAL_STATUSES}
        if status.lower() not in matches:
            return {
                "ok": False,
                "error": "usage: /goal status %s" % "|".join(codex_config.GOAL_STATUSES),
            }
        if not self._ensure_goal_thread():
            return {"ok": False, "error": "Codex thread is not ready"}
        status = matches[status.lower()]
        params = {"threadId": self.thread_id, "status": status}
        res = self._client().request("thread/goal/set", params, timeout=30) or {}
        goal = self._goal_from_response(res) or {"objective": "", "status": status}
        self._codex_notice("Goal status set: " + self._goal_summary(goal), "thread/goal/set", goal)
        self._persist()
        return {"ok": True, "command": "goal", "action": "status", "status": status, "goal": goal}

    def clear_goal(self):
        if not self._ensure_goal_thread():
            return {"ok": False, "error": "Codex thread is not ready"}
        self._client().request("thread/goal/clear", {"threadId": self.thread_id}, timeout=30)
        self._codex_notice("Goal cleared", "thread/goal/clear")
        self._persist()
        return {"ok": True, "command": "goal", "action": "clear"}

    def _split_words(self, text, expected=0):
        try:
            words = shlex.split(str(text or ""), posix=True)
        except ValueError:
            words = str(text or "").split()
        if expected and len(words) < expected:
            return None
        return words

    def _mcp_result_events(self, call_id, name, input_obj, result, method):
        self._record_and_broadcast({
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "id": call_id, "name": name, "input": input_obj or {}}]},
        })
        self._record_and_broadcast({
            "type": "user",
            "message": {"content": [{"type": "tool_result", "tool_use_id": call_id,
                                      "content": codex_text.compact_json(result or {}, 5000)}]},
        })
        self._codex_notice("%s completed" % name, method, result, silent=True)

    def read_mcp_resource(self, arg):
        words = self._split_words(arg, expected=2)
        if not words:
            return {"ok": False, "error": "usage: /mcp-resource <server> <uri>"}
        server, uri = words[0], words[1]
        self._ensure_thread()
        params = {"server": server, "uri": uri, "threadId": self.thread_id}
        result = self._client().request("mcpServer/resource/read", params, timeout=45) or {}
        call_id = "mcp-resource-%s-%d" % (server, int(time.time() * 1000))
        self._mcp_result_events(call_id, "mcpServer.resource/read", params, result, "mcpServer/resource/read")
        return {"ok": True, "command": "mcp-resource", "server": server, "uri": uri}

    def list_mcp_status(self, arg):
        return codex_mcp_status.list_mcp_status(self.session, arg)

    def list_mcp_resources(self, arg):
        return codex_mcp_status.list_mcp_resources(self.session, arg)

    def list_skills(self, arg):
        return codex_inventory.list_skills(self.session, arg)

    def list_plugins(self, arg):
        return codex_inventory.list_plugins(self.session, arg)

    def account_status(self, arg):
        return codex_account.account_status(self.session, arg)

    def command_exec(self, arg):
        return codex_command_exec.run_command_exec(self.session, arg)

    def call_mcp_tool(self, arg):
        parts = str(arg or "").split(None, 2)
        if len(parts) < 2:
            return {"ok": False, "error": "usage: /mcp-tool <server> <tool> [json-args]"}
        server, tool = parts[0], parts[1]
        args = {}
        if len(parts) > 2 and parts[2].strip():
            try:
                args = json.loads(parts[2])
            except Exception as exc:
                return {"ok": False, "error": "invalid JSON args: %s" % exc}
            if not isinstance(args, dict):
                return {"ok": False, "error": "json-args must be an object"}
        self._ensure_thread()
        if not self.thread_id:
            return {"ok": False, "error": "Codex thread is not ready"}
        params = {"server": server, "tool": tool, "threadId": self.thread_id, "arguments": args}
        result = self._client().request("mcpServer/tool/call", params, timeout=120) or {}
        call_id = "mcp-tool-%s-%s-%d" % (server, tool, int(time.time() * 1000))
        self._mcp_result_events(call_id, "%s.%s" % (server, tool), args, result, "mcpServer/tool/call")
        return {"ok": True, "command": "mcp-tool", "server": server, "tool": tool}

