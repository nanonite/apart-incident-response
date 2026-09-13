/**
 * The only Pi extension mounted by the controller.
 *
 * This file registers the narrow public tool set and forwards calls over the
 * controller's private IPC endpoint. It never opens the board database, reads
 * arbitrary files, runs a command, or accepts identity fields from the model.
 */

import { createConnection, Socket } from "node:net";
import { open, readFile } from "node:fs/promises";
import { Type } from "typebox";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const SOCKET_ENV = "APART_TOOL_SOCKET";
const modelProvider = (process.env.APART_MODEL ?? "").split("/", 1)[0];
const opencodeSession = process.env.APART_OPENCODE_SESSION;
const opencodeUserAgent = process.env.APART_OPENCODE_USER_AGENT;
const condition = process.env.APART_CONDITION;
const capabilityProfile = process.env.APART_CAPABILITY_PROFILE ?? "task-diagnostic-v1";
const hasTaskQuery = capabilityProfile === "task-diagnostic-v1";
const OPENROUTER_TOP_LOGPROBS = 5;

if (condition !== "C0" && condition !== "C1" && condition !== "C2") {
	throw new Error("APART_CONDITION must be C0, C1, or C2");
}

type ToolResponse = {
	ok: boolean;
	result?: unknown;
	error?: { code?: string; message?: string };
};

async function serviceConfiguration(): Promise<{
	socketPath?: string;
	requestFifo?: string;
	responseFifo?: string;
	credential: string;
}> {
	const socketPath = process.env[SOCKET_ENV];
	const requestFifo = process.env.APART_TOOL_REQUEST_FIFO;
	const responseFifo = process.env.APART_TOOL_RESPONSE_FIFO;
	const credentialFile = process.env.APART_CONTROLLER_CREDENTIAL_FILE;
	const hasFifo = requestFifo !== undefined || responseFifo !== undefined;
	if ((!socketPath && !hasFifo) || (socketPath && hasFifo) || !credentialFile) {
		throw new Error("controller tool service is unavailable");
	}
	if ((requestFifo === undefined) !== (responseFifo === undefined)) {
		throw new Error("controller tool FIFO configuration is incomplete");
	}
	const credential = (await readFile(credentialFile, "utf8")).trim();
	if (!credential) throw new Error("controller tool credential is empty");
	return { socketPath, requestFifo, responseFifo, credential };
}

async function callFifo(
	requestPath: string,
	responsePath: string,
	payload: string,
	signal: AbortSignal | undefined,
): Promise<string> {
	if (signal?.aborted) throw new Error("tool request cancelled");
	const request = await open(requestPath, "w");
	await request.writeFile(payload);
	await request.close();
	const response = await open(responsePath, "r");
	const chunks: Buffer[] = [];
	const buffer = Buffer.alloc(4096);
	try {
		while (true) {
			const read = await response.read(buffer, 0, buffer.length, null);
			if (read.bytesRead === 0) break;
			chunks.push(Buffer.from(buffer.subarray(0, read.bytesRead)));
			if (chunks[chunks.length - 1].includes(10)) break;
		}
	} finally {
		await response.close();
	}
	return Buffer.concat(chunks).toString("utf8").split("\n", 1)[0];
}

function readLine(socket: Socket, signal: AbortSignal | undefined): Promise<string> {
	return new Promise((resolve, reject) => {
		let response = "";
		let settled = false;
		const timer = setTimeout(() => finish(new Error("tool service timed out")), 5000);
		const abort = () => finish(new Error("tool request cancelled"));

		const finish = (error: Error | null, value?: string) => {
			if (settled) return;
			settled = true;
			clearTimeout(timer);
			signal?.removeEventListener("abort", abort);
			socket.removeAllListeners();
			socket.destroy();
			if (error) reject(error);
			else resolve(value ?? "");
		};

		signal?.addEventListener("abort", abort, { once: true });
		socket.setEncoding("utf8");
		socket.on("data", (chunk: string) => {
			response += chunk;
			if (response.length > 128 * 1024) {
				finish(new Error("tool service response exceeded the size limit"));
				return;
			}
			const newline = response.indexOf("\n");
			if (newline >= 0) finish(null, response.slice(0, newline));
		});
		socket.on("error", (error) => finish(new Error(`tool service connection failed: ${error.message}`)));
		socket.on("close", () => {
			if (!settled) finish(new Error("tool service closed the connection"));
		});
	});
}

async function callService(
	operation: string,
	input: Record<string, unknown>,
	signal: AbortSignal | undefined,
): Promise<unknown> {
	const { socketPath, requestFifo, responseFifo, credential } = await serviceConfiguration();
	const request = JSON.stringify({ credential, operation, arguments: input }) + "\n";
	if (requestFifo && responseFifo) {
		const decoded = JSON.parse(await callFifo(requestFifo, responseFifo, request, signal)) as ToolResponse;
		if (!decoded.ok) throw new Error(decoded.error?.message ?? "tool request rejected");
		return decoded.result;
	}
	const socket = createConnection({ path: socketPath });
	const response = readLine(socket, signal);
	socket.once("connect", () => socket.write(request));
	const decoded = JSON.parse(await response) as ToolResponse;
	if (!decoded.ok) {
		throw new Error(decoded.error?.message ?? "tool request rejected");
	}
	return decoded.result;
}

function result(value: unknown) {
	return {
		content: [{ type: "text" as const, text: JSON.stringify(value) }],
		details: value,
	};
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null && !Array.isArray(value);
}

export default function (pi: ExtensionAPI) {
	if (modelProvider === "openrouter") {
		// The OpenRouter provider is OpenAI-compatible, so this public payload hook
		// adds the narrow request fields needed by the per-turn capture in Pi's
		// streaming adapter. It leaves stream, tools, retries, and all other Pi
		// request fields untouched.
		pi.on("before_provider_request", (event) => {
			if (!isRecord(event.payload)) return;
			const provider = isRecord(event.payload.provider) ? event.payload.provider : {};
			return {
				...event.payload,
				logprobs: true,
				top_logprobs: OPENROUTER_TOP_LOGPROBS,
				provider: {
					...provider,
					order: ["openai"],
					allow_fallbacks: false,
					require_parameters: true,
				},
			};
		});
	}

	if (modelProvider === "opencode-go") {
		if (!opencodeSession || !opencodeUserAgent) {
			throw new Error("OpenCode Go session headers are unavailable");
		}
		pi.on("before_provider_headers", (event) => {
			event.headers["x-opencode-session"] = opencodeSession;
			event.headers["x-opencode-client"] = "apart-incident-response";
			event.headers["User-Agent"] = opencodeUserAgent;
		});
	}

	pi.registerTool({
		name: "task_read",
		label: "Read task file",
		description: "Read one permitted UTF-8 file from the authenticated task fixture.",
		parameters: Type.Object({
			path: Type.String({ minLength: 1, maxLength: 256 }),
		}),
		async execute(_toolCallId, params, signal) {
			return result(await callService("task_read", params, signal));
		},
	});

	if (hasTaskQuery) {
		pi.registerTool({
			name: "task_query",
			label: "Query task files",
			description: "Search permitted task files for a literal, case-insensitive text query.",
			parameters: Type.Object({
				query: Type.String({ minLength: 1, maxLength: 256 }),
				path: Type.Optional(Type.String({ minLength: 1, maxLength: 256 })),
				max_results: Type.Optional(Type.Integer({ minimum: 1, maximum: 50 })),
			}),
			async execute(_toolCallId, params, signal) {
				return result(await callService("task_query", params, signal));
			},
		});
	}

	pi.registerTool({
		name: "task_submit",
		label: "Submit task diagnosis",
		description: "Submit one structured diagnosis with cited evidence for the authenticated task.",
		executionMode: "sequential",
		parameters: Type.Object({
			diagnosis: Type.String({ minLength: 1, maxLength: 16 * 1024 }),
			evidence: Type.Array(
				Type.Object({
					path: Type.String({ minLength: 1, maxLength: 256 }),
					excerpt: Type.Optional(Type.String({ minLength: 1, maxLength: 4 * 1024 })),
					line_start: Type.Optional(Type.Integer({ minimum: 1 })),
					line_end: Type.Optional(Type.Integer({ minimum: 1 })),
				}),
				{ minItems: 1, maxItems: 32 },
			),
		}),
		async execute(_toolCallId, params, signal) {
			return result(await callService("task_submit", params, signal));
		},
	});

	if (condition === "C0") return;

	pi.registerTool({
		name: "board_read",
		label: "Read message board",
		description: "Read the next bounded page of messages after a sequence cursor.",
		parameters: Type.Object({
			after_sequence_id: Type.Optional(Type.Integer({ minimum: 0 })),
			limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 50 })),
		}),
		async execute(_toolCallId, params, signal) {
			return result(await callService("board_read", params, signal));
		},
	});

	pi.registerTool({
		name: "board_append",
		label: "Append message",
		// The service supplies run and agent identity from the credential.
		description: "Append one bounded diagnostic message to the service-owned board.",
		executionMode: "sequential",
		parameters: Type.Object({
			message: Type.String({ minLength: 1, maxLength: 8 * 1024 }),
		}),
		async execute(_toolCallId, params, signal) {
			return result(await callService("board_append", params, signal));
		},
	});
}
