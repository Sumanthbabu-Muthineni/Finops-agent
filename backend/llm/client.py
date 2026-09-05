import json
import re
from typing import Dict, Any, List, Optional
import httpx
from backend.config import settings
from backend.core.models import FinancialQueryAST, AnomalyInfo

class BaseLLMClient:
    def complete(self, prompt: str, system: str = "") -> str:
        raise NotImplementedError

class OllamaClient(BaseLLMClient):
    def __init__(self):
        self.base_url = settings.OLLAMA_BASE_URL.rstrip("/v1")
        self.model = settings.OLLAMA_MODEL

    def complete(self, prompt: str, system: str = "") -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        try:
            with httpx.Client(timeout=30.0) as client:
                res = client.post(
                    f"{self.base_url}/api/chat",
                    json={"model": self.model, "messages": messages, "stream": False, "format": "json"}
                )
                if res.status_code == 200:
                    data = res.json()
                    return data.get("message", {}).get("content", "")
                else:
                    raise RuntimeError(f"Ollama error {res.status_code}: {res.text}")
        except Exception as e:
            # Fall back to mock if Ollama is not active
            return MockLLMClient().complete(prompt, system)

class BedrockClient(BaseLLMClient):
    def __init__(self):
        import boto3
        client_kwargs = {
            "service_name": "bedrock-runtime",
            "region_name": settings.AWS_REGION
        }
        if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
            client_kwargs["aws_access_key_id"] = settings.AWS_ACCESS_KEY_ID
            client_kwargs["aws_secret_access_key"] = settings.AWS_SECRET_ACCESS_KEY
            
        self.client = boto3.client(**client_kwargs)
        self.model_id = settings.BEDROCK_MODEL_ID

    def complete(self, prompt: str, system: str = "") -> str:
        try:
            messages = [{"role": "user", "content": [{"text": prompt}]}]
            system_prompts = [{"text": system}] if system else []

            response = self.client.converse(
                modelId=self.model_id,
                messages=messages,
                system=system_prompts,
                inferenceConfig={"temperature": 0.0, "maxTokens": 800}
            )
            return response["output"]["message"]["content"][0]["text"]
        except Exception as e:
            return MockLLMClient().complete(prompt, system)

class GroqClient(BaseLLMClient):
    def __init__(self):
        from groq import Groq
        self.client = Groq(api_key=settings.GROQ_API_KEY)
        self.model = settings.GROQ_MODEL

    def complete(self, prompt: str, system: str = "") -> str:
        try:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.0,
                response_format={"type": "json_object"}
            )
            return response.choices[0].message.content
        except Exception:
            return MockLLMClient().complete(prompt, system)

class MockLLMClient(BaseLLMClient):
    """Deterministic, zero-latency 8B emulator for automated testing and offline development."""
    def complete(self, prompt: str, system: str = "") -> str:
        from backend.engine.db import db
        from backend.core.entity_resolver import entity_resolver
        from datetime import datetime, timedelta

        lower = prompt.lower()
        anchor = db.get_anchor_date()
        val_map = db.get_value_to_column_map()
        schema_profile = db.get_schema_profile()

        # 1. Resolve bank/entity dynamically from session / query
        is_global = bool(re.search(
            r"\b(all entities|all banks|all accounts|every bank|across all|select all|for all entities|for all banks|for all|all of them|everyone)\b",
            lower
        ))
        bank_match, _, _, _, _ = entity_resolver.resolve_with_session(prompt)
        filters = []
        if bank_match and not is_global:
            filters.append({"field": "bank_name", "operator": "eq", "value": bank_match})

        # Check for reference ID lookup (e.g. '1715499972', 'HDFCH01078329532', 'S31125841', 'REF...')
        ref_match = re.search(r"\b([A-Z0-9]{8,20}|\d{9,15})\b", prompt)
        if ref_match and not any(w in lower for w in ["program", "account"]):
            cand_ref = ref_match.group(1)
            if not any(cand_ref.upper() == b for b in getattr(entity_resolver, "bank_codes", [])):
                filters.append({"field": "transaction_reference_id", "operator": "eq", "value": cand_ref})

        # Check for Program ID (e.g. 'program 21', 'program 46')
        prog_match = re.search(r"\bprogram\s+(\d+)\b", lower)
        if prog_match:
            filters.append({"field": "program_id", "operator": "eq", "value": int(prog_match.group(1))})

        # 2. Dynamic Schema Linking: detect mentioned categorical values & columns
        matched_cols_to_vals: Dict[str, List[Dict[str, str]]] = {}
        for val_key, mappings in val_map.items():
            # Skip bank_name as bank is handled by entity_resolver
            non_bank_mappings = [m for m in mappings if m["column"] not in ["bank_name", "bank_code"]]
            if not non_bank_mappings:
                continue
            if re.search(r"\b" + re.escape(val_key) + r"\b", lower):
                for m in non_bank_mappings:
                    col = m["column"]
                    if col not in matched_cols_to_vals:
                        matched_cols_to_vals[col] = []
                    if not any(existing["canonical"] == m["canonical"] for existing in matched_cols_to_vals[col]):
                        matched_cols_to_vals[col].append(m)

        # 3. Detect dynamic group_by
        group_by = []
        all_cols = set()
        for d_cols in schema_profile.values():
            all_cols.update(d_cols.keys())

        # Check if credit vs debit breakdown requested
        if ("credit" in lower and "debit" in lower) or "by transaction type" in lower or "by type" in lower:
            group_by.append("transaction_type")
        elif "by bank" in lower or "breakdown by bank" in lower or "compare by bank" in lower:
            group_by.append("bank_name")
        elif "by program" in lower or "breakdown by program" in lower:
            group_by.append("program_id")

        for col in all_cols:
            col_clean = col.replace("_", " ")
            if re.search(r"\b(breakdown by|group by|compare by|by)\s+" + re.escape(col_clean) + r"\b", lower) or \
               re.search(r"\b(breakdown by|group by|compare by|by)\s+" + re.escape(col) + r"\b", lower):
                if col not in group_by and col not in ["transaction_amount", "amount", "transaction_date", "available_balance", "balance"]:
                    group_by.append(col)

        # 4. If single value matched and not grouped on that column, add as filter
        for col, val_list in matched_cols_to_vals.items():
            if col not in group_by:
                for v_item in val_list:
                    if not any(f.get("field") == col for f in filters):
                        filters.append({"field": col, "operator": "eq", "value": v_item["canonical"]})

        # 5. Detect target domain dynamically based on query intent
        if any(w in lower for w in ["balance", "balances", "available balance", "account balance"]):
            target_domain = "accounts"
            target_metric = "available_balance"
        elif any(f.get("field") == "transaction_reference_id" for f in filters):
            target_domain = "transactions"
            target_metric = "records_list"
        else:
            target_domain = "transactions"
            target_metric = "total_amount" if group_by else ("records_list" if any(w in lower for w in ["who paid", "show", "list", "which", "lookup"]) and not any(w in lower for w in ["how much", "what amount", "total", "spend"]) else "total_amount")

        # 6. Date Range handling
        date_range = None
        if "start_date" in prompt:
            m_start = re.search(r'"start_date":\s*"([^"]+)"', prompt)
            m_end = re.search(r'"end_date":\s*"([^"]+)"', prompt)
            if m_start and m_end:
                date_range = {"start_date": m_start.group(1), "end_date": m_end.group(1)}

        if not date_range and target_domain == "transactions":
            try:
                a_dt = datetime.strptime(anchor, "%Y-%m-%d")
                if "last month" in lower:
                    first_cur = a_dt.replace(day=1)
                    last_prev = first_cur - timedelta(days=1)
                    first_prev = last_prev.replace(day=1)
                    date_range = {
                        "start_date": first_prev.strftime("%Y-%m-%d"),
                        "end_date": last_prev.strftime("%Y-%m-%d")
                    }
                elif "june 2026" in lower:
                    date_range = {"start_date": "2026-06-01", "end_date": "2026-06-30"}
                elif "may 2026" in lower:
                    date_range = {"start_date": "2026-05-01", "end_date": "2026-05-31"}
                elif "2026" in lower:
                    date_range = {"start_date": "2026-01-01", "end_date": "2026-12-31"}
                elif "2025" in lower:
                    date_range = {"start_date": "2025-01-01", "end_date": "2025-12-31"}
            except Exception:
                pass

        return json.dumps({
            "target_domain": target_domain,
            "target_metric": target_metric,
            "entity_filters": filters,
            "date_range": date_range,
            "group_by": group_by,
            "order_by_desc": True,
            "limit": 100
        })

class LLMAdapter:
    def __init__(self):
        provider = settings.LLM_PROVIDER.lower()
        if provider == "bedrock":
            self.client = BedrockClient()
        elif provider == "groq" and settings.GROQ_API_KEY:
            self.client = GroqClient()
        elif provider == "ollama":
            self.client = OllamaClient()
        else:
            self.client = MockLLMClient()

    def generate_ast(
        self,
        query: str,
        resolved_vendor: Optional[str] = None,
        anchor_date: Optional[str] = None,
        last_ast: Optional[Dict[str, Any]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        active_context_vendor: Optional[str] = None,
        session_confirmed_entities: Optional[Dict[str, str]] = None
    ) -> FinancialQueryAST:
        from backend.engine.db import db
        anchor = anchor_date or db.get_anchor_date()
        canonical_banks = db.get_distinct_entities().get("banks", [])
        schema_profile = db.get_schema_profile()

        system_prompt = (
            "You are a strict Financial AST Generator for an 8B model. "
            "Convert natural language banking queries into a typed JSON Abstract Syntax Tree.\n"
            f"The evaluation anchor date for 'today/now' is {anchor}.\n"
            f"Available canonical banks: {json.dumps(canonical_banks)}.\n"
            f"Database Schema Profile (Available domains, columns, data types, and sample values):\n"
            f"{json.dumps(schema_profile, indent=2)}\n\n"
            "SCHEMA-DRIVEN REASONING & MULTI-TURN PRINCIPLES:\n"
            "1. TARGET DOMAINS:\n"
            "   - 'transactions': for payments, inflows, outflows, debits, credits, transfers, transaction dates, or reference ID lookups.\n"
            "   - 'accounts': for available balances, account lists, program IDs, or entity balances.\n"
            "   - 'banks': for high-level bank totals across accounts.\n"
            "2. GROUPING & MULTI-VALUE COMPARISONS:\n"
            "   - When the user asks for amounts across credit vs debit (e.g. 'credit vs debit', 'how much was credited and debited'), "
            "set group_by to [\"transaction_type\"] and target_metric to \"total_amount\".\n"
            "   - When the user asks for amounts or balances by bank, set group_by to [\"bank_name\"].\n"
            "   - When comparing across programs, set group_by to [\"program_id\"].\n"
            "3. BALANCE QUERIES: When the user inquires about available balance, set target_domain to 'accounts' and target_metric to 'available_balance'.\n"
            "4. SENSITIVE DATA MASKING: Never expose unmasked raw account numbers. Accounts are referenced by masked number (e.g. ending in 9069).\n"
            "5. REFERENCE ID SEARCH: If the user provides a reference receipt number (e.g. '1715499972'), add an entity_filter on 'transaction_reference_id'.\n"
            "6. MULTI-TURN CONTEXT: Inherit previous turn's date_range and bank filters when user asks follow-up questions in the same session.\n"
            "7. ALL ENTITIES / GLOBAL SCOPE: If user asks for 'all entities', 'all banks', or 'across all', do not filter on a single bank.\n\n"
            "Output valid JSON ONLY matching the FinancialQueryAST schema:\n"
            "{\n"
            "  \"target_domain\": \"transactions\" | \"accounts\" | \"banks\",\n"
            "  \"target_metric\": \"total_amount\" | \"available_balance\" | \"average_amount\" | \"record_count\" | \"records_list\",\n"
            "  \"entity_filters\": [{\"field\": string, \"operator\": \"eq\", \"value\": any}],\n"
            "  \"date_range\": {\"start_date\": \"YYYY-MM-DD\", \"end_date\": \"YYYY-MM-DD\"} | null,\n"
            "  \"group_by\": string[],\n"
            "  \"order_by_desc\": true,\n"
            "  \"limit\": 100\n"
            "}"
        )

        user_content = ""
        if conversation_history:
            user_content += "Recent Conversation History:\n"
            for msg in conversation_history[-4:]:
                role = "User" if msg["role"] == "user" else "Assistant"
                user_content += f"- {role}: {msg.get('content', '')[:120]}\n"
        if active_context_vendor:
            user_content += f"Active Session Vendor Context: '{active_context_vendor}'\n"
        if session_confirmed_entities:
            user_content += f"Session Confirmed Aliases: {json.dumps(session_confirmed_entities)}\n"
        if resolved_vendor:
            user_content += f"Resolved Vendor Match: '{resolved_vendor}'\n"
        if last_ast:
            user_content += f"Previous AST Context: {json.dumps(last_ast)}\n"
        user_content += f"Current User Query: '{query}'\n"

        raw_output = self.client.complete(user_content, system_prompt)

        # Robust JSON extraction
        try:
            match = re.search(r'\{.*\}', raw_output, re.DOTALL)
            json_str = match.group(0) if match else raw_output
            parsed = json.loads(json_str)

            # Check if query is global across all entities
            is_global_q = bool(re.search(
                r"\b(all entities|all vendors|all companies|all accounts|every vendor|across all|select all|for all entities|for all vendors|for all companies|for all|all of them|everyone)\b",
                query.lower()
            ))

            # Ensure resolved vendor is present in filters if provided and query is not global
            if is_global_q:
                parsed["entity_filters"] = [f for f in parsed.get("entity_filters", []) if f.get("field") != "vendor_name"]
            elif resolved_vendor:
                filters = parsed.get("entity_filters", [])
                has_vendor = any(f.get("field") == "vendor_name" for f in filters)
                if not has_vendor:
                    filters.append({"field": "vendor_name", "operator": "eq", "value": resolved_vendor})
                parsed["entity_filters"] = filters

            # Context inheritance: If follow-up query didn't specify date_range, inherit from last_ast
            if last_ast and not parsed.get("date_range") and last_ast.get("date_range"):
                if not any(w in query.lower() for w in ["all time", "ever", "entire", "history", "all years"]):
                    parsed["date_range"] = last_ast["date_range"]

            # Universal Group-By Auto-Inference: If multiple values of the same column were filtered, ensure group_by
            if not parsed.get("group_by"):
                col_val_counts: Dict[str, int] = {}
                for f in parsed.get("entity_filters", []):
                    col = f.get("field")
                    if col in ["vendor_name", "currency"]:
                        continue
                    if f.get("operator") == "in" and isinstance(f.get("value"), list) and len(f.get("value")) >= 2:
                        parsed["group_by"] = [col]
                        parsed["target_metric"] = "total_amount"
                        break
                    if col:
                        col_val_counts[col] = col_val_counts.get(col, 0) + 1
                if not parsed.get("group_by"):
                    for col, count in col_val_counts.items():
                        if count >= 2:
                            parsed["group_by"] = [col]
                            parsed["target_metric"] = "total_amount"
                            break

            return FinancialQueryAST(**parsed)
        except Exception:
            # Fallback to deterministic mock interpretation
            mock_out = MockLLMClient().complete(user_content)
            return FinancialQueryAST(**json.loads(mock_out))

    def synthesize_narrative(
        self,
        query: str,
        metrics: Dict[str, Any],
        anomaly: AnomalyInfo,
        sample_rows: List[Dict[str, Any]],
        breakdown_items: Optional[List[Dict[str, Any]]] = None,
        resolved_vendor: Optional[str] = None
    ) -> str:
        """Generates grounded narrative without performing any arithmetic."""
        parts = []

        if breakdown_items and len(breakdown_items) > 0:
            prefix = f"For **{resolved_vendor}**, " if resolved_vendor else ""
            item_descriptions = []
            for item in breakdown_items:
                name = item.get("name", "")
                amt = item.get("amount", 0.0)
                cnt = item.get("count", 0)
                cnt_str = f" ({cnt} record{'s' if cnt != 1 else ''})" if cnt else ""
                item_descriptions.append(f"**${amt:,.2f}** is **{name}**{cnt_str}")

            total = metrics.get("total_amount")
            total_str = f", totaling **${float(total):,.2f}**" if total is not None and len(breakdown_items) > 1 else ""
            parts.append(f"{prefix}" + " and ".join(item_descriptions) + f"{total_str}.")
        else:
            total = metrics.get("total_amount")
            count = metrics.get("record_count")
            avg = metrics.get("average_amount")
            is_balance_q = any(w in query.lower() for w in ["balance", "balances", "available balance", "account balance"])

            if len(sample_rows) == 1 and any(w in query.lower() for w in ["reference", "receipt", "lookup", "ref"]):
                row = sample_rows[0]
                bank = row.get("bank_name") or row.get("bank_code") or ""
                amt = float(row.get("transaction_amount") or row.get("amount") or 0.0)
                t_type = (row.get("transaction_type") or "transaction").upper()
                ref = row.get("transaction_reference_id") or row.get("reference_id") or ""
                acc = row.get("masked_account_number") or ""
                parts.append(f"Found matching **{t_type}** transaction: reference **{ref}** for **${amt:,.2f}** at **{bank}** (Account {acc}).")
            elif total is not None and count is not None:
                noun = "accounts" if is_balance_q else "transactions"
                lead = "Total available balance is" if is_balance_q else "Total calculated is"
                parts.append(f"{lead} **${float(total):,.2f}** across **{count}** {noun}.")
                if avg is not None and not is_balance_q:
                    parts.append(f"The average transaction was **${float(avg):,.2f}**.")
            elif count is not None:
                parts.append(f"Found **{count}** matching records.")
            elif len(sample_rows) > 0:
                parts.append(f"Retrieved **{len(sample_rows)}** transactions matching your request.")
            else:
                parts.append("No matching records found in the database.")

        if anomaly.detected:
            parts.append(f"⚠️ **Anomaly Alert:** {anomaly.message}")

        return " ".join(parts)

llm_adapter = LLMAdapter()
