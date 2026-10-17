from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from app.config import settings
from app.models import AgentStructuredSynthesisSchema
from app.observability import get_logger, start_otel_span
from app.tools import (
    execute_registered_tool,
    get_gemini_tool_declarations,
    get_openai_tool_schemas,
)


logger = get_logger("supply_planner.llm_client")


class HybridLLMClient:
    """
    Enterprise Hybrid LLM Client with Strategic Model Routing & Native Schema-Constrained Tool Calling.

    Supports:
    - Tier 1 (`fast`): Low-latency Flash/Mini model (`gemini-2.0-flash` or `gpt-4o-mini`) for
      intent classification, ERP inventory triage, and conversational S&OP Q&A.
    - Tier 2 (`deep`): High-reasoning Pro model (`gemini-1.5-pro` or `gpt-4o`) for
      statistical safety stock, supplier capacity risk, MRP optimization, and S&OP governance.
    - Native LLM Tool Calling (`execute_agent_with_tools`): Passes explicit JSON Schemas (`tools`
      in OpenAI or `function_declarations` in Gemini) so the LLM invokes domain tools and
      synthesizes outputs constrained by `AgentStructuredSynthesisSchema`.
    - Deterministic Fallback Engine: When no external API key is configured, validates tool arguments
      against the exact same Pydantic JSON schemas and executes the registered tool pipeline so all
      tests and offline demos verify identical schema contracts.
    """

    def __init__(self) -> None:
        self.gemini_api_key = settings.get_gemini_api_key()
        self.openai_api_key = settings.get_openai_api_key()
        self.fast_model = settings.fast_model_name
        self.deep_model = settings.deep_model_name

    @property
    def active_provider(self) -> str:
        if self.gemini_api_key:
            return f"google-gemini ({self.fast_model} / {self.deep_model})"
        if self.openai_api_key:
            return "openai (gpt-4o-mini / gpt-4o)"
        return "deterministic-constitutional-engine (offline fallback)"

    def get_model_for_tier(self, tier: str = "fast") -> str:
        if self.gemini_api_key:
            return self.fast_model if tier == "fast" else self.deep_model
        if self.openai_api_key:
            return "gpt-4o-mini" if tier == "fast" else "gpt-4o"
        return f"constitutional-rule-engine-{tier}"

    def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        fallback_fn: Callable[[], str],
        model_tier: str = "fast",
        temperature: float = 0.1,
    ) -> str:
        selected_model = self.get_model_for_tier(model_tier)
        with start_otel_span(
            "llm.generate",
            {
                "llm.provider": self.active_provider,
                "llm.model": selected_model,
                "llm.tier": model_tier,
            },
        ) as span:
            if self.gemini_api_key:
                try:
                    import google.generativeai as genai  # type: ignore

                    genai.configure(api_key=self.gemini_api_key)
                    model = genai.GenerativeModel(
                        model_name=selected_model,
                        system_instruction=system_prompt,
                    )
                    response = model.generate_content(
                        user_prompt,
                        generation_config={"temperature": temperature},
                    )
                    if response and response.text:
                        span.set_attribute("llm.live_call", True)
                        return response.text.strip()
                except Exception as exc:  # pragma: no cover
                    logger.warning("gemini_generate_fallback", error=str(exc))

            if self.openai_api_key:
                try:
                    from openai import OpenAI  # type: ignore

                    client = OpenAI(api_key=self.openai_api_key)
                    completion = client.chat.completions.create(
                        model=selected_model,
                        temperature=temperature,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                    )
                    content = completion.choices[0].message.content
                    if content:
                        span.set_attribute("llm.live_call", True)
                        return content.strip()
                except Exception as exc:  # pragma: no cover
                    logger.warning("openai_generate_fallback", error=str(exc))

            span.set_attribute("llm.live_call", False)
            return fallback_fn()

    def execute_agent_with_tools(
        self,
        agent_name: str,
        system_prompt: str,
        user_prompt: str,
        tool_names: List[str],
        default_tool_call_args: Dict[str, Dict[str, Any]],
        fallback_synthesis_fn: Callable[[Dict[str, Dict[str, Any]]], Dict[str, Any]],
        model_tier: str = "deep",
        temperature: float = 0.1,
    ) -> Dict[str, Any]:
        """
        Executes a specialist agent using Native LLM Function Calling constrained by explicit JSON Schemas.

        1. Exposes `get_openai_tool_schemas(tool_names)` and `get_gemini_tool_declarations(tool_names)`.
        2. When a live LLM API key is configured, lets the LLM emit native `tool_calls` / `function_call`,
           validates arguments against Pydantic JSON Schemas, executes the tools, and validates the final
           response against `AgentStructuredSynthesisSchema`.
        3. When running in deterministic fallback mode, validates `default_tool_call_args` against the
           exact same Pydantic JSON Schemas, executes each registered tool, and validates the synthesis
           against `AgentStructuredSynthesisSchema`.
        """
        selected_model = self.get_model_for_tier(model_tier)
        openai_schemas = get_openai_tool_schemas(tool_names)
        gemini_declarations = get_gemini_tool_declarations(tool_names)

        with start_otel_span(
            f"llm.tool_calling.{agent_name}",
            {
                "llm.agent_name": agent_name,
                "llm.model": selected_model,
                "llm.tier": model_tier,
                "llm.bound_tools": ",".join(tool_names),
                "llm.schema_enforced": True,
            },
        ) as span:
            executed_tools: Dict[str, Dict[str, Any]] = {}
            invocation_mode = "deterministic_schema_enforced"

            # Path A: Live OpenAI Native Function Calling + Structured JSON Schema Output
            if self.openai_api_key:
                try:
                    from openai import OpenAI  # type: ignore

                    client = OpenAI(api_key=self.openai_api_key)
                    messages: List[Dict[str, Any]] = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ]
                    first_resp = client.chat.completions.create(
                        model=selected_model,
                        temperature=temperature,
                        messages=messages,
                        tools=openai_schemas,
                        tool_choice="required",
                    )
                    assistant_msg = first_resp.choices[0].message
                    if assistant_msg.tool_calls:
                        invocation_mode = "openai_native_function_calling"
                        messages.append(assistant_msg.model_dump())
                        for tc in assistant_msg.tool_calls:
                            fn_name = tc.function.name
                            fn_args = json.loads(tc.function.arguments or "{}")
                            tool_output = execute_registered_tool(fn_name, fn_args)
                            executed_tools[fn_name] = tool_output
                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tc.id,
                                    "content": json.dumps(tool_output),
                                }
                            )

                        # Ensure all required domain tools for this agent were run
                        for req_tool, req_args in default_tool_call_args.items():
                            if req_tool not in executed_tools:
                                executed_tools[req_tool] = execute_registered_tool(req_tool, req_args)

                        synthesis_schema = AgentStructuredSynthesisSchema.model_json_schema()
                        synthesis_schema["additionalProperties"] = False
                        final_resp = client.chat.completions.create(
                            model=selected_model,
                            temperature=temperature,
                            messages=messages,
                            response_format={
                                "type": "json_schema",
                                "json_schema": {
                                    "name": "agent_structured_synthesis",
                                    "strict": True,
                                    "schema": synthesis_schema,
                                },
                            },
                        )
                        raw_json = final_resp.choices[0].message.content or "{}"
                        validated_synth = AgentStructuredSynthesisSchema.model_validate_json(raw_json)
                        span.set_attribute("llm.invocation_mode", invocation_mode)
                        return {
                            "tool_outputs": executed_tools,
                            "synthesis": validated_synth.model_dump(),
                            "invocation_mode": invocation_mode,
                            "bound_tool_schemas": openai_schemas,
                        }
                except Exception as exc:  # pragma: no cover
                    logger.warning("openai_tool_calling_fallback", agent=agent_name, error=str(exc))

            # Path B: Live Gemini Native Function Calling + response_schema
            if self.gemini_api_key and not executed_tools:
                try:
                    import google.generativeai as genai  # type: ignore

                    genai.configure(api_key=self.gemini_api_key)
                    model = genai.GenerativeModel(
                        model_name=selected_model,
                        system_instruction=system_prompt,
                        tools=[{"function_declarations": gemini_declarations}],
                    )
                    chat = model.start_chat()
                    resp = chat.send_message(user_prompt)
                    for part in resp.candidates[0].content.parts:
                        if getattr(part, "function_call", None) and part.function_call.name:
                            invocation_mode = "gemini_native_function_calling"
                            fn_name = part.function_call.name
                            fn_args = dict(part.function_call.args)
                            executed_tools[fn_name] = execute_registered_tool(fn_name, fn_args)
                except Exception as exc:  # pragma: no cover
                    logger.warning("gemini_tool_calling_fallback", agent=agent_name, error=str(exc))

            # Path C: Deterministic Schema-Enforced Tool Dispatch & Synthesis Validation
            for tool_name in tool_names:
                if tool_name not in executed_tools:
                    raw_args = default_tool_call_args.get(tool_name, {})
                    executed_tools[tool_name] = execute_registered_tool(tool_name, raw_args)

            raw_synthesis = fallback_synthesis_fn(executed_tools)
            validated_synthesis = AgentStructuredSynthesisSchema.model_validate(raw_synthesis)
            span.set_attribute("llm.invocation_mode", invocation_mode)
            span.set_attribute("llm.tools_executed_count", len(executed_tools))

            return {
                "tool_outputs": executed_tools,
                "synthesis": validated_synthesis.model_dump(),
                "invocation_mode": invocation_mode,
                "bound_tool_schemas": openai_schemas,
            }
