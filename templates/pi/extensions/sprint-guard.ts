/**
 * Viking host caps for Pi in this workspace only (copied by workspace_init).
 *
 * 20-turn child budget, strip thinking from the next prompt, cap tool text,
 * and block bash scans of main_disasm.asm.
 *
 * Turn cap / disasm block apply only to `pi --no-session` children
 * (official subagent spawn). Thinking strip + tool cap apply to this project.
 */
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const MAX_CHILD_TURNS = 20;
const MAX_TOOL_CHARS = 4096;
const DISASM = "main_disasm.asm";

function isSubagentChild(): boolean {
	return process.argv.includes("--no-session");
}

function textOf(content: unknown): string {
	if (typeof content === "string") return content;
	if (!Array.isArray(content)) return "";
	return content
		.map((part) => (part && typeof part === "object" && "text" in part ? String(part.text ?? "") : ""))
		.join("");
}

function truncateContent(content: unknown, maxChars: number): unknown {
	if (typeof content === "string") {
		if (content.length <= maxChars) return content;
		return `${content.slice(0, maxChars)}\n[sprint-guard truncated ${content.length} chars → ${maxChars}]`;
	}
	if (!Array.isArray(content)) return content;
	return content.map((part) => {
		if (!part || typeof part !== "object" || !("text" in part) || typeof part.text !== "string") {
			return part;
		}
		if (part.text.length <= maxChars) return part;
		return {
			...part,
			text: `${part.text.slice(0, maxChars)}\n[sprint-guard truncated ${part.text.length} chars → ${maxChars}]`,
		};
	});
}

function stripThinking(content: unknown): unknown {
	if (!Array.isArray(content)) return content;
	const next = content.filter((part) => {
		if (!part || typeof part !== "object" || !("type" in part)) return true;
		return part.type !== "thinking" && part.type !== "reasoning";
	});
	return next.length === content.length ? content : next;
}

export default function (pi: ExtensionAPI) {
	let turnIndex = 0;
	const child = isSubagentChild();

	pi.on("agent_start", () => {
		turnIndex = 0;
	});

	pi.on("turn_end", (event) => {
		turnIndex = event.turnIndex + 1;
	});

	pi.on("context", (event) => {
		const messages = event.messages.map((msg) => {
			if (msg.role === "assistant") {
				return { ...msg, content: stripThinking(msg.content) };
			}
			if (msg.role === "toolResult") {
				return { ...msg, content: truncateContent(msg.content, MAX_TOOL_CHARS) };
			}
			return msg;
		});
		return { messages };
	});

	pi.on("tool_result", (event) => {
		const raw = textOf(event.content);
		if (raw.length <= MAX_TOOL_CHARS) return;
		return { content: truncateContent(event.content, MAX_TOOL_CHARS) };
	});

	if (!child) return;

	pi.on("tool_call", (event) => {
		const name = event.toolName;
		const input = (event.input ?? {}) as Record<string, unknown>;
		const command = String(input.command ?? "");

		if (turnIndex >= MAX_CHILD_TURNS) {
			if (name === "bash" && command.includes("sprint-done")) return;
			return {
				block: true,
				reason:
					`TURN_CAP ${MAX_CHILD_TURNS}: stop exploring. Call viking_bridge.py sprint-done --status YIELD|FAIL now.`,
			};
		}

		if (name === "bash" && command.includes(DISASM) && !command.includes("viking_bridge")) {
			return {
				block: true,
				reason:
					`Do not bash ${DISASM}. Use viking_bridge.py grep --uri viking://... --pattern ... --context 8 (dest to VFS).`,
			};
		}
	});
}
