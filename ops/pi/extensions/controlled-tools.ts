// Pi 1.1.0 only. No shell, nested tools, provider registration, or lifecycle retries.
import { readFileSync } from "node:fs";
import { normalize } from "../lab/pi-wire-guard.mjs";
const definitions = JSON.parse(readFileSync(new URL("./tool-schemas.json", import.meta.url), "utf8"));
const phases = {
  analysis: ["observe_metrics", "read_source", "candidate_status"],
  plan: ["observe_metrics", "read_source", "propose_plan", "candidate_status"],
  develop: ["read_source", "apply_patch", "run_check", "candidate_status"],
  diagnose: ["observe_metrics", "read_source", "candidate_status"],
};
export default function (api) {
  const names = phases[process.env.PI_TOOL_PHASE];
  const url = new URL(process.env.PI_TOOL_BROKER_URL || "invalid:");
  const token = process.env.PI_TOOL_SCOPE_TOKEN;
  if (!names || url.protocol !== "http:" || url.hostname !== "127.0.0.1" || !url.port ||
      url.pathname !== "/" || url.username || url.password || url.search || url.hash || !token) throw new Error("invalid controlled tool config");
  const active = definitions.filter(d => names.includes(d.name));
  api.on("before_provider_request", event => normalize(event.payload, active));
  api.on("tool_call", event => {
    if (!names.includes(event.toolName) || event.parentToolCallId || !/^[A-Za-z0-9_-]{1,128}$/.test(event.toolCallId))
      return { block: true, reason: "ungranted or nested tool" };
  });
  for (const d of definitions) api.registerTool({
    name: d.name, label: d.name, description: d.description, parameters: d.input_schema,
    exposure: "model-only", defaultActive: false, executionMode: "sequential", constrainedSampling: false,
    async execute(callId, args, signal) {
      const body = JSON.stringify({tool:d.name,call_id:callId,arguments:args});
      if (!names.includes(d.name) || Buffer.byteLength(body) > 32768) throw new Error("ungranted or oversized tool");
      const deadline = AbortSignal.timeout(30000);
      const requestSignal = AbortSignal.any([...(signal ? [signal] : []), deadline]);
      const transportError = () => new Error(requestSignal.aborted
        ? (deadline.aborted && requestSignal.reason === deadline.reason
          ? "controlled broker deadline exceeded" : "controlled broker aborted")
        : "controlled broker transport failure");
      let response;
      try {
        response = await fetch(new URL("/v1/tools", url), {method:"POST",redirect:"error",
          headers:{"Content-Type":"application/json","x-api-key":token,"X-Pi-Scope":"local-trial-1"},
          body, signal: requestSignal});
      } catch { throw transportError(); }
      const status = response.status;
      if (!Number.isInteger(status) || status < 100 || status > 599) throw new Error("controlled broker invalid HTTP status");
      if (status < 200 || status >= 300) {
        const reason = status === 400 ? "input rejected"
          : status === 401 || status === 403 ? "authentication rejected"
          : status === 408 ? "deadline exceeded"
          : status === 409 ? "state conflict"
          : status === 429 ? "rate limited"
          : status >= 500 ? "server error" : "HTTP rejected";
        throw new Error(`controlled broker ${reason} (HTTP ${status})`);
      }
      let raw;
      try { raw = await response.text(); } catch { throw transportError(); }
      if (Buffer.byteLength(raw) > 65536) throw new Error("oversized broker receipt");
      let receipt;
      try { receipt = JSON.parse(raw); } catch { throw new Error("invalid broker receipt"); }
      if (receipt.schema_version !== 1 || !["done","blocked","failed","uncertain"].includes(receipt.status) ||
          typeof receipt.operation_id !== "string" || typeof receipt.evidence !== "object") throw new Error("invalid broker receipt");
      return {content:[{type:"text",text:JSON.stringify(receipt)}],details:{receipt},isError:receipt.status !== "done"};
    },
  });
  api.on("session_start", () => api.setActiveTools(names));
}
