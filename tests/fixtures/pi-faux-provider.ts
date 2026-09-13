/** Deterministic, in-process model provider for the direct Pi smoke test. */

import {
	fauxAssistantMessage,
	fauxProvider,
	fauxToolCall,
} from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
	const fixture = fauxProvider({
		api: "faux",
		provider: "fixture",
		models: [{ id: "smoke", name: "Credential-free Pi smoke model" }],
		tokenSize: { min: 1, max: 1 },
	});
	fixture.setResponses([
		fauxAssistantMessage(fauxToolCall("task_read", { path: "evidence.txt" }, { id: "read-1" }), {
			stopReason: "toolUse",
		}),
		fauxAssistantMessage(fauxToolCall("task_query", { query: "ORCHID-731" }, { id: "query-1" }), {
			stopReason: "toolUse",
		}),
		fauxAssistantMessage(fauxToolCall("board_append", { message: "Pi agent: ORCHID-731" }, { id: "append-1" }), {
			stopReason: "toolUse",
		}),
		fauxAssistantMessage(fauxToolCall("board_read", { limit: 10 }, { id: "board-read-1" }), {
			stopReason: "toolUse",
		}),
		fauxAssistantMessage(fauxToolCall("task_submit", {
			diagnosis: "The ORCHID-731 configuration revision changed CACHE_MODE from local to shared, causing the cache-related outage.",
			evidence: [{ path: "evidence.txt", excerpt: "ORCHID-731 fixture" }],
		}, { id: "submit-1" }), {
			stopReason: "toolUse",
		}),
		fauxAssistantMessage("Pi direct smoke complete"),
	]);
	pi.registerProvider(fixture.provider);
}
